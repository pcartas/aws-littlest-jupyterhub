"""
Commandline interface for setting config items in config.yaml.

Used as:

tljh-config set firstlevel.second_level something

tljh-config show

tljh-config show firstlevel

tljh-config show firstlevel.second_level
"""

import argparse
import os
import re
import sys
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy

import requests
from filelock import FileLock, Timeout

from .yaml import yaml

INSTALL_PREFIX = os.environ.get("TLJH_INSTALL_PREFIX", "/opt/tljh")
HUB_ENV_PREFIX = os.path.join(INSTALL_PREFIX, "hub")
USER_ENV_PREFIX = os.path.join(INSTALL_PREFIX, "user")
STATE_DIR = os.path.join(INSTALL_PREFIX, "state")
CONFIG_DIR = os.path.join(INSTALL_PREFIX, "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")
USERNAME_PREFIX = os.getenv("TLJH_USERNAME_PREFIX", "jupyter-")
HASH_USERNAME = os.getenv("TLJH_HASH_USERNAME", True)


@contextmanager
def config_file_lock(config_path, timeout=1):
    """Context manager to acquire the config file lock"""
    lock_file = f"{config_path}.lock"
    try:
        with FileLock(lock_file).acquire(timeout=timeout):
            yield

    except Timeout:
        print(
            f"Another instance of tljh-config holds the lock {lock_file}.",
            file=sys.stderr,
        )
        sys.exit(1)


def set_item_in_config(config, property_path, value):
    """
    Set key at property_path to value in config & return new config.

    config is not mutated.

    property_path is a series of dot separated values. Any part of the path
    that does not exist is created.
    """
    path_components = property_path.split(".")

    # Mutate a copy of the config, not config itself
    cur_part = config_copy = deepcopy(config)
    for i, cur_path in enumerate(path_components):
        cur_path = path_components[i]
        if i == len(path_components) - 1:
            # Final component
            cur_part[cur_path] = value
        else:
            # If we are asked to create new non-leaf nodes, we will always make them dicts
            # This means setting is *destructive* - will replace whatever is down there!
            if cur_path not in cur_part or not _is_dict(cur_part[cur_path]):
                cur_part[cur_path] = {}
            cur_part = cur_part[cur_path]

    return config_copy


def unset_item_from_config(config, property_path):
    """
    Unset key at property_path in config & return new config.

    config is not mutated.

    property_path is a series of dot separated values.
    """
    path_components = property_path.split(".")

    # Mutate a copy of the config, not config itself
    cur_part = config_copy = deepcopy(config)

    def remove_empty_configs(configuration, path):
        """
        Delete the keys that hold an empty dict.

        This might happen when we delete a config property
        that has no siblings from a multi-level config.
        """
        if not path:
            return configuration
        conf_iter = configuration
        for cur_path in path:
            if conf_iter[cur_path] == {}:
                del conf_iter[cur_path]
                remove_empty_configs(configuration, path[:-1])
            else:
                conf_iter = conf_iter[cur_path]

    for i, cur_path in enumerate(path_components):
        if i == len(path_components) - 1:
            if cur_path not in cur_part:
                raise ValueError(f"{property_path} does not exist in config!")
            del cur_part[cur_path]
            remove_empty_configs(config_copy, path_components[:-1])
            break
        else:
            if cur_path not in cur_part:
                raise ValueError(f"{property_path} does not exist in config!")
            cur_part = cur_part[cur_path]

    return config_copy


def add_item_to_config(config, property_path, value):
    """
    Add an item to a list in config.
    """
    path_components = property_path.split(".")

    # Mutate a copy of the config, not config itself
    cur_part = config_copy = deepcopy(config)
    for i, cur_path in enumerate(path_components):
        if i == len(path_components) - 1:
            # Final component, it must be a list and we append to it
            if cur_path not in cur_part or not _is_list(cur_part[cur_path]):
                cur_part[cur_path] = []
            cur_part = cur_part[cur_path]

            cur_part.append(value)
        else:
            # If we are asked to create new non-leaf nodes, we will always make them dicts
            # This means setting is *destructive* - will replace whatever is down there!
            if cur_path not in cur_part or not _is_dict(cur_part[cur_path]):
                cur_part[cur_path] = {}
            cur_part = cur_part[cur_path]

    return config_copy


def remove_item_from_config(config, property_path, value):
    """
    Remove an item from a list in config.
    """
    path_components = property_path.split(".")

    # Mutate a copy of the config, not config itself
    cur_part = config_copy = deepcopy(config)
    for i, cur_path in enumerate(path_components):
        if i == len(path_components) - 1:
            # Final component, it must be a list and we delete from it
            if cur_path not in cur_part or not _is_list(cur_part[cur_path]):
                raise ValueError(f"{property_path} is not a list")
            cur_part = cur_part[cur_path]
            cur_part.remove(value)
        else:
            if cur_path not in cur_part or not _is_dict(cur_part[cur_path]):
                raise ValueError(f"{property_path} does not exist in config!")
            cur_part = cur_part[cur_path]

    return config_copy


def validate_config(config, validate):
    """
    Validate changes to the config with tljh-config against the schema
    """
    import jsonschema

    from .config_schema import config_schema

    try:
        jsonschema.validate(instance=config, schema=config_schema)
    except jsonschema.exceptions.ValidationError as e:
        if validate:
            print(
                f"Config validation error: {e.message}.\n"
                "You can still apply this change without validation by re-running your command with the --no-validate flag.\n"
                "If you think this validation error is incorrect, please report it to https://github.com/jupyterhub/the-littlest-jupyterhub/issues.",
                file=sys.stderr,
            )
            sys.exit(1)


def show_config(config_path):
    """
    Pretty print config from given config_path
    """
    config = get_current_config(config_path)
    yaml.dump(config, sys.stdout)


def set_config_value(config_path, key_path, value, validate=True):
    """
    Set key at key_path in config_path to value
    """
    with config_file_lock(config_path):
        config = get_current_config(config_path)
        config = set_item_in_config(config, key_path, value)
        validate_config(config, validate)

        with open(config_path, "w") as f:
            yaml.dump(config, f)


def unset_config_value(config_path, key_path, validate=True):
    """
    Unset key at key_path in config_path
    """
    with config_file_lock(config_path):
        config = get_current_config(config_path)
        config = unset_item_from_config(config, key_path)
        validate_config(config, validate)

        with open(config_path, "w") as f:
            yaml.dump(config, f)


def add_config_value(config_path, key_path, value, validate=True):
    """
    Add value to list at key_path
    """
    with config_file_lock(config_path):
        config = get_current_config(config_path)
        config = add_item_to_config(config, key_path, value)
        validate_config(config, validate)

        with open(config_path, "w") as f:
            yaml.dump(config, f)


def remove_config_value(config_path, key_path, value, validate=True):
    """
    Remove value from list at key_path
    """
    with config_file_lock(config_path):
        config = get_current_config(config_path)
        config = remove_item_from_config(config, key_path, value)
        validate_config(config, validate)

        with open(config_path, "w") as f:
            yaml.dump(config, f)


def get_current_config(config_path):
    """
    Retrieve the current config at config_path
    """
    try:
        with open(config_path) as f:
            return yaml.load(f)
    except FileNotFoundError:
        return {}


def check_hub_ready():
    """
    Checks that hub is running.
    """
    from .configurer import load_config

    base_url = load_config()["base_url"]
    base_url = base_url[:-1] if base_url[-1] == "/" else base_url
    http_address = load_config()["http"]["address"]
    http_port = load_config()["http"]["port"]
    # The default config is an empty address, so it binds on all interfaces.
    # Test the connectivity on the local address.
    if http_address == "":
        http_address = "127.0.0.1"
    try:
        r = requests.get(
            "http://%s:%d%s/hub/api" % (http_address, http_port, base_url), verify=False
        )
        if r.status_code != 200:
            print(f"Hub not ready: (HTTP status {r.status_code})")
        return r.status_code == 200
    except Exception as e:
        print(f"Hub not ready: {e}")
        return False


def reload_component(component):
    """
    Reload a TLJH component.

    component can be 'hub' or 'proxy'.
    """
    # import here to avoid circular imports
    from tljh import systemd, traefik

    if component == "hub":
        systemd.restart_service("jupyterhub")
        # Ensure hub is back up
        while not systemd.check_service_active("jupyterhub"):
            time.sleep(1)
        while not check_hub_ready():
            time.sleep(1)
        print("Hub reload with new configuration complete")
    elif component == "proxy":
        traefik.ensure_traefik_config(STATE_DIR)
        systemd.restart_service("traefik")
        while not systemd.check_service_active("traefik"):
            time.sleep(1)
        print("Proxy reload with new configuration complete")


def parse_value(value_str):
    """Parse a value string"""
    if value_str is None:
        return value_str
    if re.match(r"^\d+$", value_str):
        return int(value_str)
    elif re.match(r"^\d+\.\d*$", value_str):
        return float(value_str)
    elif value_str.lower() == "true":
        return True
    elif value_str.lower() == "false":
        return False
    else:
        # it's a string
        return value_str


def _is_dict(item):
    return isinstance(item, Mapping)


def _is_list(item):
    return isinstance(item, Sequence)


def main(argv=None):
    if os.geteuid() != 0:
        print("tljh-config needs root privileges to run", file=sys.stderr)
        print(
            "Try using sudo before the tljh-config command you wanted to run",
            file=sys.stderr,
        )
        sys.exit(1)

    if argv is None:
        argv = sys.argv[1:]

    from .log import init_logging

    try:
        init_logging()
    except Exception as e:
        print(str(e))
        print("Perhaps you didn't use `sudo -E`?")

    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        "--config-path", default=CONFIG_FILE, help="Path to TLJH config.yaml file"
    )

    argparser.add_argument(
        "--validate", action="store_true", help="Validate the TLJH config"
    )
    argparser.add_argument(
        "--no-validate",
        dest="validate",
        action="store_false",
        help="Do not validate the TLJH config",
    )
    argparser.set_defaults(validate=True)

    subparsers = argparser.add_subparsers(dest="action")

    show_parser = subparsers.add_parser("show", help="Show current configuration")

    unset_parser = subparsers.add_parser("unset", help="Unset a configuration property")
    unset_parser.add_argument(
        "key_path", help="Dot separated path to configuration key to unset"
    )

    set_parser = subparsers.add_parser("set", help="Set a configuration property")
    set_parser.add_argument(
        "key_path", help="Dot separated path to configuration key to set"
    )
    set_parser.add_argument("value", help="Value to set the configuration key to")

    add_item_parser = subparsers.add_parser(
        "add-item", help="Add a value to a list for a configuration property"
    )
    add_item_parser.add_argument(
        "key_path", help="Dot separated path to configuration key to add value to"
    )
    add_item_parser.add_argument("value", help="Value to add to the configuration key")

    remove_item_parser = subparsers.add_parser(
        "remove-item", help="Remove a value from a list for a configuration property"
    )
    remove_item_parser.add_argument(
        "key_path", help="Dot separated path to configuration key to remove value from"
    )
    remove_item_parser.add_argument("value", help="Value to remove from key_path")

    reload_parser = subparsers.add_parser(
        "reload", help="Reload a component to apply configuration change"
    )
    reload_parser.add_argument(
        "component",
        choices=("hub", "proxy"),
        help="Which component to reload",
        default="hub",
        nargs="?",
    )

    args = argparser.parse_args(argv)

    if args.action == "show":
        show_config(args.config_path)
    elif args.action == "set":
        set_config_value(
            args.config_path, args.key_path, parse_value(args.value), args.validate
        )
    elif args.action == "unset":
        unset_config_value(args.config_path, args.key_path, args.validate)
    elif args.action == "add-item":
        add_config_value(
            args.config_path, args.key_path, parse_value(args.value), args.validate
        )
    elif args.action == "remove-item":
        remove_config_value(
            args.config_path, args.key_path, parse_value(args.value), args.validate
        )
    elif args.action == "reload":
        reload_component(args.component)
    else:
        argparser.print_help()


if __name__ == "__main__":
    main()
