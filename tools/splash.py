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

from urllib.parse import urlsplit, urlunsplit

import flask  # pylint: disable=E0401

from pylon.core.tools.context import Context as Holder  # pylint: disable=E0611,E0401
from pylon.core.tools import log, config  # pylint: disable=E0611,E0401,W0611

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
    # Allow auth flow so admins can sign in while maintenance is active
    auth_allowlist = this.descriptor.config.get(
        "splash_auth_allowlist",
        ["/forward-auth/", "/auth/", "/api/v1/auth/"],
    )
    for prefix in auth_allowlist:
        if source_uri.startswith(prefix):
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
    auth_status = None
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
        else:
            # Unauthenticated: honor redirect so browsers can reach the login flow.
            # Without this, admins hit 503 before ever loading the login page.
            if auth_status.get("action") == "redirect" and auth_status.get("target"):
                return _make_redirect_app(auth_status["target"])
            #
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
        # Logged-in non-admin: block with splash.
        return maintenance_splash_app
    #
    # Anonymous visitor (no cookie, or session resolved to public via a
    # public rule). Redirect to the login page so admins can sign in.
    login_url = _resolve_login_url(source, headers)
    if login_url is not None:
        return _make_redirect_app(login_url)
    #
    return maintenance_splash_app


def _resolve_login_url(source, headers):
    """ Ask auth_authorize for the login redirect URL by pretending the
    request is for a non-public URI. Strip target_to so post-login the
    user lands on the auth provider's default (usually "/"). """
    forced_source = dict(source)
    forced_source["uri"] = f"{context.url_prefix}/__maintenance_login__"
    try:
        forced = context.rpc_manager.timeout(15).auth_authorize(
            forced_source, dict(headers), {},
        )
    except:  # pylint: disable=W0702
        log.debug("splash: forced auth_authorize failed", exc_info=True)
        return None
    #
    if forced.get("auth_ok"):
        return None
    if forced.get("action") != "redirect":
        return None
    target = forced.get("target")
    if not target:
        return None
    #
    parsed = urlsplit(target)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _make_redirect_app(target):
    """ WSGI app that issues a 302 to the given location """
    def _redirect_app(_environ, start_response):
        start_response("302 Found", [
            ("Location", target),
            ("Cache-Control", "no-store, no-cache, max-age=0, must-revalidate"),
        ])
        return [b""]
    return _redirect_app


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
