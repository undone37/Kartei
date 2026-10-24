"""Messages for the UI that are stored as text (export status, import warnings, sync status).

Encoded as "@code {json params}"; the SPA translates them via msg.<code>. Anything else (e.g. an SMTP or Graph error)
is shown as it is.
"""
import json


def msg(code, **params):
    return f"@{code} {json.dumps(params, ensure_ascii=False, default=str)}"
