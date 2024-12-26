from typing import Optional, Any, IO, Generator
import time
from urllib.parse import parse_qs
from pathlib import Path
import requests
import blackboxprotobuf


# it's too long, so it is stored separately
from .message_types import FINALIZE_MESSAGE_TYPE

REQUESTS_TIMEOUT = 10


def get_auth_token(auth_data: str, timeout: Optional[int] = REQUESTS_TIMEOUT) -> dict[str, str]:
    """
    Send auth request to get bearer token.

    Args:
        auth_data (str): URL-encoded authentication data.
        timeout (Optional[int], optional): Request timeout in seconds. Defaults to REQUESTS_TIMEOUT.

    Returns:
        Dict[str, str]: Parsed authentication response with token and other details.

    Raises:
        requests.HTTPError: If the authentication request fails.
    """
    auth_data_dict = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(auth_data).items()}

    request_auth_data = {
        "androidId": auth_data_dict["androidId"],
        "app": "com.google.android.apps.photos",
        "client_sig": auth_data_dict["client_sig"],
        "callerPkg": "com.google.android.apps.photos",
        "callerSig": auth_data_dict["callerSig"],
        "device_country": auth_data_dict["device_country"],
        "Email": auth_data_dict["Email"],
        "google_play_services_version": auth_data_dict["google_play_services_version"],
        "lang": auth_data_dict["lang"],
        "oauth2_foreground": auth_data_dict["oauth2_foreground"],
        "sdk_version": auth_data_dict["sdk_version"],
        "service": auth_data_dict["service"],
        "Token": auth_data_dict["Token"],
    }

    headers = {
        "Accept-Encoding": "gzip",
        "app": "com.google.android.apps.photos",
        "Connection": "Keep-Alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "device": request_auth_data["androidId"],
        "User-Agent": "GoogleAuth/1.4 (Pixel XL PQ2A.190205.001); gzip",
    }

    response = requests.post("https://android.googleapis.com/auth", headers=headers, data=request_auth_data, timeout=timeout)
    response.raise_for_status()

    parsed_auth_response = {}
    for line in response.text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed_auth_response[key] = value

    return parsed_auth_response


def get_upload_token(sha_hash_b64: str, file_size: int, auth_token: str, timeout: Optional[int] = REQUESTS_TIMEOUT) -> str:
    """
    Obtain an upload token from the Google Photos API.

    Args:
        sha_hash_b64 (str): Base64-encoded SHA-1 hash of the file.
        file_size (int): Size of the file in bytes.
        auth_token (str): Authentication token.
        timeout (Optional[int], optional): Request timeout in seconds. Defaults to REQUESTS_TIMEOUT.

    Returns:
        str: Upload token for the file.

    Raises:
        requests.HTTPError: If the upload token request fails.
    """
    message_type = {"1": {"type": "int"}, "2": {"type": "int"}, "3": {"type": "int"}, "4": {"type": "int"}, "7": {"type": "int"}}
    proto_body = {"1": 2, "2": 1, "3": 1, "4": 3, "7": file_size}

    serialized_data = blackboxprotobuf.encode_message(proto_body, message_type)

    headers = {
        "Accept-Encoding": "gzip",
        "Accept-Language": "en_US",
        "Content-Type": "application/x-protobuf",
        "User-Agent": "com.google.android.apps.photos/49029607 (Linux; U; Android 9; en_US; Pixel XL; Build/PQ2A.190205.001; Cronet/127.0.6510.5) (gzip)",
        "Authorization": f"Bearer {auth_token}",
        "X-Goog-Hash": f"sha1={sha_hash_b64}",
        "X-Upload-Content-Length": str(file_size),
    }

    response = requests.post("https://photos.googleapis.com/data/upload/uploadmedia/interactive", headers=headers, data=serialized_data, timeout=timeout)
    response.raise_for_status()
    return response.headers["X-GUploader-UploadID"]


def find_remote_media_by_hash(sha1_hash: bytes, auth_token: str, timeout: Optional[int] = REQUESTS_TIMEOUT) -> Optional[str]:
    """
    Check library for existing files with the hash.

    Args:
        sha1_hash (bytes): SHA-1 hash of the file.
        auth_token (str): Authentication token.
        timeout (Optional[int], optional): Request timeout in seconds. Defaults to REQUESTS_TIMEOUT.

    Returns:
        Optional[str]: Media key of the existing file, or None if not found.

    Raises:
        requests.HTTPError: If the media search request fails.
    """
    message_type = {"1": {"field_order": ["1", "2"], "message_typedef": {"1": {"field_order": ["1"], "message_typedef": {"1": {"type": "bytes"}}, "type": "message"}, "2": {"message_typedef": {}, "type": "message"}}, "type": "message"}}
    proto_body = {"1": {"1": {"1": sha1_hash}, "2": {}}}
    serialized_data = blackboxprotobuf.encode_message(proto_body, message_type)
    headers = {
        "Accept-Encoding": "gzip",
        "Accept-Language": "en_US",
        "Content-Type": "application/x-protobuf",
        "User-Agent": "com.google.android.apps.photos/49029607 (Linux; U; Android 9; en_US; Pixel XL; Build/PQ2A.190205.001; Cronet/127.0.6510.5) (gzip)",
        "Authorization": f"Bearer {auth_token}",
    }
    response = requests.post("https://photosdata-pa.googleapis.com/6439526531001121323/5084965799730810217", headers=headers, data=serialized_data, timeout=timeout)
    response.raise_for_status()

    decoded_message, _ = blackboxprotobuf.decode_message(response.content)
    media_key = decoded_message["1"].get("2", {}).get("2", {}).get("1", None)
    return media_key


def upload_file(file: str | Path | bytes | IO[bytes] | Generator[bytes, None, None], upload_token: str, auth_token: str, timeout: Optional[int] = REQUESTS_TIMEOUT) -> dict[str, Any]:
    """
    Upload a file to Google Photos.

    Args:
        file (Union[str, Path, bytes, IO[bytes], Generator[bytes, None, None]]):
            The file to upload. Can be a path (str or Path), bytes, BufferedReader, or a generator yielding bytes.
        upload_token (str): Upload token from `get_upload_token()`.
        auth_token (str): Auth token from `get_auth_token()`.
        progress (bool, optional): Display upload progress. Defaults to False.
        timeout (Optional[int], optional): Request timeout in seconds. Defaults to REQUESTS_TIMEOUT.

    Returns:
        Dict[str, Any]: Decoded upload response.

    Raises:
        requests.HTTPError: If the file upload fails.
    """

    headers = {
        "Accept-Encoding": "gzip",
        "Accept-Language": "en_US",
        "User-Agent": "com.google.android.apps.photos/49029607 (Linux; U; Android 9; en_US; Pixel XL; Build/PQ2A.190205.001; Cronet/127.0.6510.5) (gzip)",
        "Authorization": f"Bearer {auth_token}",
    }

    if isinstance(file, (str, Path)):
        with Path(file).open("rb") as f:
            response = requests.put(
                f"https://photos.googleapis.com/data/upload/uploadmedia/interactive?upload_id={upload_token}",
                headers=headers,
                data=f,
                timeout=timeout,
            )
    else:
        response = requests.put(
            f"https://photos.googleapis.com/data/upload/uploadmedia/interactive?upload_id={upload_token}",
            headers=headers,
            data=file,
            timeout=timeout,
        )

    response.raise_for_status()

    upload_response_decoded, _ = blackboxprotobuf.decode_message(response.content)
    return upload_response_decoded


def finalize_upload(upload_response_decoded: dict[str, Any], file_name: str, sha1_hash: bytes, auth_token: str, timeout: Optional[int] = REQUESTS_TIMEOUT) -> str:
    """
    Finalize the upload by sending the complete message to the API.

    Args:
        upload_response_decoded (Dict[str, Any]): Decoded upload response.
        file_name (str): Name of the uploaded file.
        sha1_hash (bytes): SHA-1 hash of the file.
        auth_token (str): Authentication token.
        timeout (Optional[int], optional): Request timeout in seconds. Defaults to REQUESTS_TIMEOUT.

    Returns:
        str: Media key of the uploaded file.

    Raises:
        requests.HTTPError: If the finalization request fails.
    """

    message_type = FINALIZE_MESSAGE_TYPE
    proto_body = {
        "1": {
            "1": {
                "1": 2,
                "2": upload_response_decoded["2"],
            },
            "2": file_name,
            "3": sha1_hash,
            "4": {"1": int(time.time()), "2": 46000000},
            "7": 3,
            "8": {
                "1": {
                    "1": "",
                    "3": "",
                    "4": "",
                    "5": {"1": "", "2": "", "3": "", "4": "", "5": "", "7": ""},
                    "6": "",
                    "7": {"2": ""},
                    "15": "",
                    "16": "",
                    "17": "",
                    "19": "",
                    "20": "",
                    "21": {"5": {"3": ""}, "6": ""},
                    "25": "",
                    "30": {"2": ""},
                    "31": "",
                    "32": "",
                    "33": {"1": ""},
                    "34": "",
                    "36": "",
                    "37": "",
                    "38": "",
                    "39": "",
                    "40": "",
                    "41": "",
                },
                "5": {
                    "2": {"2": {"3": {"2": ""}, "4": {"2": ""}}, "4": {"2": {"2": 1}}, "5": {"2": ""}, "6": 1},
                    "3": {"2": {"3": "", "4": ""}, "3": {"2": "", "3": {"2": 1}}, "4": "", "5": {"2": {"2": 1}}, "7": ""},
                    "4": {"2": {"2": ""}},
                    "5": {"1": {"2": {"3": "", "4": ""}, "3": {"2": "", "3": {"2": 1}}}, "3": 1},
                },
                "8": "",
                "9": {"2": "", "3": {"1": "", "2": ""}, "4": {"1": {"3": {"1": {"1": {"5": {"1": ""}, "6": ""}, "2": "", "3": {"1": {"5": {"1": ""}, "6": ""}, "2": ""}}}, "4": {"1": {"2": ""}}}}},
                "11": {"2": "", "3": "", "4": {"2": {"1": 1, "2": 2}}},
                "12": "",
                "14": {"2": "", "3": "", "4": {"2": {"1": 1, "2": 2}}},
                "15": {"1": "", "4": ""},
                "17": {"1": "", "4": ""},
                "19": {"2": "", "3": "", "4": {"2": {"1": 1, "2": 2}}},
                "22": "",
                "23": "",
            },
            "10": 1,
            "17": 0,
        },
        "2": {"3": "Pixel XL", "4": "Google", "5": 28},  # changing this to other make and model will make uploads take up storage
        "3": bytes([1, 3]),
    }

    serialized_data = blackboxprotobuf.encode_message(proto_body, message_type)

    headers = {
        "Accept-Encoding": "gzip",
        "Accept-Language": "en_US",
        "Content-Type": "application/x-protobuf",
        "User-Agent": "com.google.android.apps.photos/49029607 (Linux; U; Android 9; en_US; Pixel XL; Build/PQ2A.190205.001; Cronet/127.0.6510.5) (gzip)",
        "Authorization": f"Bearer {auth_token}",
        "x-goog-ext-173412678-bin": "CgcIAhClARgC",
        "x-goog-ext-174067345-bin": "CgIIAg==",
    }

    response = requests.post("https://photosdata-pa.googleapis.com/6439526531001121323/16538846908252377752", headers=headers, data=serialized_data, timeout=timeout)
    response.raise_for_status()
    decoded_message, _ = blackboxprotobuf.decode_message(response.content)
    media_key = decoded_message["1"]["3"]["1"]
    return media_key