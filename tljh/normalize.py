"""
Functions to normalize various inputs
"""

import hashlib
from tljh.config import HASH_USERNAME
import os


def generate_system_username(username):
    """
    Generate a POSIX-compliant username from the given username.

    If the username is less than 26 characters, it is returned as is.
    If the username is 26 characters or more and HASH_USERNAME is True,
    the username is truncated to 26 characters, a hyphen is appended,
    followed by the first 5 characters of the SHA-256 hash of the username.
    This ensures the resulting username is always under 32 characters.
    If HASH_USERNAME is False and the username is 32 characters or less,
    it is returned as is. Otherwise, it is truncated to 32 characters.

    Args:
        username (str): The original username.

    Returns:
        str: The generated POSIX-compliant username.
    """

    if os.getenv("TLJH_HASH_USERNAME", HASH_USERNAME).lower() == "true":
        if len(username) < 26:
            return username

        userhash = hashlib.sha256(username.encode("utf-8")).hexdigest()
        return "{username_trunc}-{hash}".format(
            username_trunc=username[:26], hash=userhash[:5]
        )
    else:
        if len(username) <= 32:
            return username
        
        return username[:32]
        
