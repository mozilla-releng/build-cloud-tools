import copy


def process_includes(data):
    """
    Iterate over a de-YAML'd data structure.  A top-level 'includes'
    is treated as a dictionary of includable chunks.  Anywhere else,
    a dictionary containing only {'include': 'somename'} will include the
    chunk named 'somename' in its place.
    """
    if not isinstance(data, dict) or 'includes' not in data:
        return data
    includes = data.pop('includes')

    def iter(d):
        if isinstance(d, dict):
            if len(d) == 1 and 'include' in d and d['include'] in includes:
                return includes[d['include']]
            return {k: iter(v) for (k, v) in d.iteritems()}
        elif isinstance(d, list):
            return [iter(v) for v in d]
        else:
            return d

    # repeatedly apply until all includes are processed (nothing changes)
    while 1:
        last_data = copy.deepcopy(data)
        data = iter(data)
        if data == last_data:
            return data
