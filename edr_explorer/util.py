import requests


def get_request(uri):
    """
    Make an HTTP GET request to the (EDR) Server at `uri`.

    """
    response = None
    status_code = None
    errors = None
    try:
        r = requests.get(uri)
    except Exception as e:
        errors = e.__class__.__name__
    else:
        response = r.json()
        status_code = r.status_code
        if "code" in response.keys() and "message" in response.keys():
            status_code = response["code"]
            errors = response["message"]
    return response, status_code, errors


def dict_list_search(l, keys, value):
    """
    Search a list of dictionaries of a common schema for a specific key/value pair.

    For example:
        l = [{'a': foo, 'b': 1, 'c': 2}, {'a': 'bar', 'b': 3, 'c': 4}]
    If `keys='a'` and `value='foo'` then the first dict in the list would be returned.

    """
    values_list = [d[keys] for d in l]
    try:
        idx = values_list.index(value)
    except ValueError:
        raise ValueError(f"A pair matching {{{keys}: {value}}} could not be found.")
    else:
        return l[idx]