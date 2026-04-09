#!/usr/bin/python3
# coding=utf-8

#   Copyright 2026 EPAM Systems
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

""" Splash """

import flask  # pylint: disable=E0401

from pylon.core.tools.context import Context as Holder  # pylint: disable=E0611,E0401
from pylon.core.tools import config  # pylint: disable=E0611,E0401,W0611

from tools import context, this  # pylint: disable=E0401


def maintenance_splash_hook(router, environ, _start_response):  # pylint: disable=R0912
    """ Router hook """
    # Construct request
    req = flask.Request(environ)
    # Collect data
    source_uri = req.full_path
    if not req.query_string and source_uri.endswith("?"):
        source_uri = source_uri[:-1]
    #
    for endpoint in ["healthz", "livez", "readyz"]:
        if source_uri.startswith(f"/{endpoint}") and f"/{endpoint}/" in router.map:
            return None
    #
    source_uri = f'{context.url_prefix}{source_uri}'
    #
    source = {
        "method": req.method,
        "proto": req.scheme,
        "host": req.host,
        "uri": source_uri,
        "ip": req.remote_addr,
        "target": "rpc",
        "scope": None,
    }
    headers = dict(req.headers.items())
    cookies = dict(req.cookies.items())
    # Check bypass cookie
    cookie_name = this.descriptor.config.get("splash_bypass_cookie", "maintenance_splash_bypass")
    cookie_value = this.descriptor.config.get("splash_bypass_token", "bypass")
    #
    if cookie_name in cookies and cookies.get(cookie_name) == cookie_value:
        return None
    # Call authorize RPC
    auth_data = Holder()
    #
    try:
        auth_status = context.rpc_manager.timeout(15).auth_authorize(source, headers, cookies)
    except:  # pylint: disable=W0702
        auth_data.type = "public"
        auth_data.id = "-"
        auth_data.reference = "-"
    else:
        if auth_status["auth_ok"]:
            auth_data.type = auth_status["headers"].get("X-Auth-Type", "public")
            auth_data.id = auth_status["headers"].get("X-Auth-ID", "-")
            auth_data.reference = auth_status["headers"].get(
                "X-Auth-Reference", "-"
            )
            #
            try:
                auth_data.id = int(auth_data.id)
            except:  # pylint: disable=W0702
                auth_data.id = "-"
        else:  # Note: may handle other cases (like 'redirect') later
            auth_data.type = "public"
            auth_data.id = "-"
            auth_data.reference = "-"
    # Check if user is admin in administration mode
    if auth_data.type == "user":
        user_id = auth_data.id
    elif auth_data.type == "token":
        token = context.rpc_manager.timeout(15).auth_get_token(token_id=auth_data.id)
        user_id = token["user_id"]
    else:
        user_id = None
    #
    if user_id is not None:
        user_roles = context.rpc_manager.timeout(15).auth_get_user_roles(user_id, "administration")
        #
        if "admin" in user_roles:
            return None
    #
    return maintenance_splash_app


def maintenance_splash_app(_environ, start_response):
    """ Splash app """
    splash_template = config.tunable_get(
        "splash_template", this.descriptor.loader.get_data("data/default_splash.html"),
    )
    #
    start_response("503 Service Unavailable", [
        ("Content-type", "text/html; charset=utf-8"),
        ("Cache-Control", "no-store, no-cache, max-age=0, must-revalidate, proxy-revalidate"),
        ("Expires", "0"),
        ("Refresh", "120"),
        ("Retry-After", "120"),
    ])
    #
    return [splash_template.strip()]
