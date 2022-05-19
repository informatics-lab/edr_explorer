import datetime
from operator import add, sub
import re

import requests


def get_request(uri):
    """
    Make an HTTP GET request to the (EDR) Server at `uri`.

    """
    response = None
    status_code = None
    errors = None
    print(uri)
    try:
        r = requests.get(uri)
    except Exception as e:
        errors = e.__class__.__name__
    else:
        response = r.json()
        status_code = r.status_code
        if "code" in response.keys():
            message_key_name = list(set(response.keys()) - set(["code"]))[0]
            status_code = response["code"]
            errors = response[message_key_name]
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


class ISO8601Expander(object):
    isofmt_short = "%Y-%m-%dT%H:%MZ"
    isofmt = "%Y-%m-%dT%H:%M:%SZ"

    def __init__(self, iso8601_string):
        self.iso8601_string = iso8601_string
        
        self._datetimes = None
        self._datetime_strings = None
        
        self._start_date = None
        self._end_date = None
        self._repeat = None
        self._duration = None

        self.element_not_set = "-1"

    @property
    def datetimes(self):
        if self._datetimes is None:
            self._build_datetimes()
        return self._datetimes
    @datetimes.setter
    def datetimes(self, value):
        self._datetimes = value

    @property
    def datetime_strings(self):
        if self._datetime_strings is None:
            self._build_datetime_strings()
        return self._datetime_strings
    @datetime_strings.setter
    def datetime_strings(self, value):
        self._datetime_strings = value

    @property
    def start_date(self):
        if self._start_date is None:
            self._classify_string()
        return self._start_date
    @start_date.setter
    def start_date(self, value):
        self._start_date = value

    @property
    def end_date(self):
        if self._end_date is None:
            self._classify_string()
        return self._end_date
    @end_date.setter
    def end_date(self, value):
        self._end_date = value

    @property
    def duration(self):
        if self._duration is None:
            self._classify_string()
        return self._duration
    @duration.setter
    def duration(self, value):
        self._duration = value

    @property
    def repeat(self):
        if self._repeat is None:
            self._classify_string()
        return self._repeat
    @repeat.setter
    def repeat(self, value):
        self._repeat = value

    def _classify_string(self):
        elements = self.iso8601_string.split("/")
        # Handle optional `--` delimiter.
        if len(elements) == 1:
            elements = self.iso8601_string.split("--")

        # Classify the types of entities we have present.
        types = []
        for element in elements:
            if element.lower().startswith("r"):
                types.append("repeat")
                self.repeat = element
            elif element.lower().startswith("p"):
                types.append("duration")
                self.duration = element
            else:
                types.append("datetime")

        # Determine if our datetime strings are start dates, end dates, or both.
        datetime_inds = [i for i, s in enumerate(types) if s == "datetime"]
        if datetime_inds == [0, 1]:
            self.start_date = elements[0]
            self.end_date = elements[1]
        elif datetime_inds == [0]:
            self.start_date = elements[0]
            self.end_date = self.element_not_set
        elif datetime_inds == [1]:
            if types[0] == "duration":
                self.start_date = self.element_not_set
                self.end_date = elements[1]
            elif types[0] == "repeat":
                self.start_date = elements[1]
                self.end_date = self.element_not_set
        else:
            raise ValueError("Bad datetime indices.")

        # Handle no duration / repeat.
        if "duration" not in types:
            self.duration = self.element_not_set
        if "repeat" not in types:
            self.repeat = self.element_not_set

    def _get_unit(self, unit_letter, dt_type):
        unit_letter = unit_letter.lower()
        if unit_letter == "y":
            result = "years"
        elif unit_letter == "m":
            if dt_type == "date":
                result = "months"
            else:
                result = "minutes"
        elif unit_letter == "d":
            result = "days"
        elif unit_letter == "h":
            result = "hours"
        else:
            raise ValueError(f"Bad unit letter: {unit_letter!r}")
        return result

    def _split_duration(self, duration_str, datetime_type):
        bits = re.split(r"(\d+[A-Z]{1})", duration_str)[1::2]
        bits_dict = {}
        for bit in bits:
            value, unit_letter = bit[:-1], bit[-1]
            unit = self._get_unit(unit_letter, datetime_type)
            bits_dict[unit] = int(value)
        return bits_dict

    def _duration_to_timedelta(self, duration_bits):
        """
        An ISO8601 duration can provide year, month, day, hour and minute elements,
        but a timedelta only accepts days, seconds, minutes, hours, weeks, and
        sub-second intervals. To convert from one to the other, we naively convert
        years and months to days, assuming a 365 day year and a 30 day month.

        """
        years = duration_bits.pop("years", 0)
        months = duration_bits.pop("months", 0)
        days = duration_bits.pop("days", 0)
        ymd_days = years*365 + months*30 + days
        if ymd_days:
            duration_bits["days"] = ymd_days
        return datetime.timedelta(**duration_bits)

    def _handle_duration(self):
        """
        Handle the duration element of the full ISO8601 string, if present.
        If it is, we convert the values in the duration into
        a `datetime.timedelta` instance.

        """
        if self.duration == self.element_not_set:
            result = None
        else:
            date_dur, time_dur = self.duration.strip("P").split("T")
            duration_bits = self._split_duration(time_dur, "time")
            if len(date_dur):
                duration_bits.update(self._split_duration(date_dur, "date"))
            result = self._duration_to_timedelta(duration_bits)
        return result

    def _handle_repeat(self):
        """
        Handle the repeat value, if present, by returning the integer number of repeats.
        If the repeat value is not present, there is implicitly just the one repeat.

        """
        if self.repeat == self.element_not_set:
            result = 1
        else:
            result = int(self.repeat.strip("R"))
        return result

    def _handle_datetime(self, ref):
        """Handle the datetime string defined by `ref` by converting it to a datetime object."""
        dt = getattr(self, f"{ref}_date")
        if dt == self.element_not_set:
            result = None
        else:
            try:
                result = datetime.datetime.strptime(dt, self.isofmt_short)
            except ValueError:
                pass
            try:
                result = datetime.datetime.strptime(dt, self.isofmt)
            except ValueError:
                pass
        return result

    def _build_datetimes(self):
        start_date = self._handle_datetime("start")
        end_date = self._handle_datetime("end")
        repeat = self._handle_repeat()
        duration = self._handle_duration()
        # print(start_date, end_date, repeat, duration)
        if start_date is not None and all([val is None for val in [end_date, duration]]):
            self.datetimes = [start_date]
        elif start_date is not None and end_date is not None:
            self.datetimes = [start_date, end_date]
        else:
            if end_date is None and start_date is not None:
                math_func = add
                date = start_date
                reverse = False
            elif start_date is None and end_date is not None:
                math_func = sub
                date = end_date
                reverse = True
            else:
                raise ValueError("Invalid ISO8601 date string.")

            self.datetimes = [date]
            for _ in range(repeat):
                new_date = math_func(date, duration)
                self.datetimes.append(new_date)
                date = new_date

            if reverse:
                self.datetimes = self.datetimes[::-1]

    def _build_datetime_strings(self):
        self.datetime_strings = [datetime.datetime.strftime(dt, self.isofmt) for dt in self.datetimes]