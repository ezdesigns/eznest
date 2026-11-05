"""The browser launch marker is presentation only, never an access gate."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def browser_page(page='/'):
    parts = urlsplit(page)
    if parts.scheme or parts.netloc or not parts.path.startswith('/'):
        raise ValueError('Open startup on a local workspace path.')
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != 'startup']
    return urlunsplit(('', '', parts.path, urlencode([*query, ('startup', '1')]), parts.fragment))
