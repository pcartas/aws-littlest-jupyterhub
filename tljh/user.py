"""
User management for tljh.

Supports minimal user & group management
"""

import grp
import pwd
import subprocess
from os.path import expanduser

# Set up plugin infrastructure
from tljh.utils import get_plugin_manager


def ensure_user(username):
    """
    Make sure a given user exists
    """
    # Check if user exists
    try:
        pwd.getpwnam(username)
        # User exists, nothing to do!
        return
    except KeyError:
        # User doesn't exist, time to create!
        pass

    subprocess.check_call(["useradd", "--create-home", username])

    subprocess.check_call(["chmod", "o-rwx", expanduser(f"~{username}")])

    pm = get_plugin_manager()
    pm.hook.tljh_new_user_create(username=username)

def ensure_user_with_s3(username, s3_bucket_dir, iam_role):
    """
    Make sure a given user exists
    """
    # Check if user exists
    try:
        pwd.getpwnam(username)
        # User exists, nothing to do!
        return
    except KeyError:
        # User doesn't exist, time to create!
        pass

    subprocess.check_call(["useradd", "--create-home", username])
    subprocess.check_call(["chmod", "o-rwx", expanduser(f"~{username}")])

    user_info = pwd.getpwnam(username)
    uid = user_info.pw_uid
    gid = user_info.pw_gid

    if s3_bucket_dir and iam_role:
        user_home_dir = expanduser(f"~{username}")
        s3_mount_dir = f"{user_home_dir}/s3bucket"
        
        # Create the S3 bucket directory for the user
        subprocess.check_call(["mkdir", "-p", s3_mount_dir])
        
        # Set appropriate permissions on the mount directory
        subprocess.check_call(["chmod", "o-rwx", s3_mount_dir])
        
        # Mount the S3 bucket with the correct uid and gid for the user
        subprocess.call([
            "s3fs", s3_bucket_dir, s3_mount_dir, 
            "-o", f"iam_role={iam_role}", 
            "-o", "complement_stat", 
            "-o", "allow_other", 
            "-o", f"uid={uid}", 
            "-o", f"gid={gid}", 
            "-o", "dbglevel=debug", 
            "-o", "umask=002", 
            "-o", "url=https://s3.amazonaws.com", 
            "-o", "nonempty"
        ])

    pm = get_plugin_manager()
    pm.hook.tljh_new_user_create(username=username)


def remove_user(username):
    """
    Remove user from system if exists
    """
    try:
        pwd.getpwnam(username)
    except KeyError:
        # User doesn't exist, nothing to do
        return

    subprocess.check_call(["deluser", "--quiet", username])


def ensure_group(groupname):
    """
    Ensure given group exists
    """
    subprocess.check_call(["groupadd", "--force", groupname])


def remove_group(groupname):
    """
    Remove group from system if exists
    """
    try:
        grp.getgrnam(groupname)
    except KeyError:
        # Group doesn't exist, nothing to do
        return

    subprocess.check_call(["delgroup", "--quiet", groupname])


def ensure_user_group(username, groupname):
    """
    Ensure given user is member of given group

    Group and User must already exist.
    """
    group = grp.getgrnam(groupname)
    if username in group.gr_mem:
        return

    subprocess.check_call(["gpasswd", "--add", username, groupname])


def remove_user_group(username, groupname):
    """
    Ensure given user is *not* a member of given group
    """
    group = grp.getgrnam(groupname)
    if username not in group.gr_mem:
        return

    subprocess.check_call(["gpasswd", "--delete", username, groupname])
