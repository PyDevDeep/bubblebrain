import urllib.parse


def add_tracking_params(url: str, session_id: str) -> str:
    """
    Adds tracking parameters to a given URL.
    Handles existing query parameters appropriately.
    """
    if not url:
        return url

    parsed = urllib.parse.urlparse(url)
    query_params = urllib.parse.parse_qs(parsed.query)

    # Add or update tracking parameters
    query_params["bot_source"] = ["direct"]
    query_params["bot_chat_id"] = [session_id]

    # Reconstruct the query string using doseq=True to handle lists properly
    new_query = urllib.parse.urlencode(query_params, doseq=True)

    # Reconstruct the full URL
    return urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )
