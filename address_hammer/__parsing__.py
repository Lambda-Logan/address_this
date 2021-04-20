from __future__ import annotations
from typing import Pattern, Match
import re
from .__types__ import *
from .__address__ import Address, RawAddress
from . import __address__ as address
from . import __regex__ as regex
from .__zipper__ import Zipper, GenericInput, EndOfInputError, Apply
from .__zipper__ import x as zipper_x

# TODO correctly handle all usps secondary unit identifiers and 1/2


class ParseError(Exception):
    "The base class for all parsing errors"
    orig: str
    reason: str

    def __init__(self, address_string: str, reason: str):
        super(ParseError, self).__init__("@ " + reason + ": " + address_string)
        self.orig = address_string
        self.reason = reason


class EndOfAddressError(ParseError):
    """
    The address parser unexpectedly reached the end of the given string.
    This is usually cause by either the 'st_name' or the 'city' consumed the entire string.
    If you get this error, you are probably missing either (a) both the st_suffix and the st_NESW or (b) a us_state.
    """

    def __init__(self, orig: str, reason: str):
        super().__init__(orig, reason + ": end of input")


class ParserConfigError(Exception):
    msg: str

    def __init__(self, msg: str):
        super(ParserConfigError, self).__init__(msg)
        self.msg = msg


class ParseStep(NamedTuple):
    label: str
    value: str


Input = GenericInput[str]


def __make_stops_on__(stop_patterns: Iter[Pattern[str]]) -> Fn[[str], bool]:
    def stops_on(s: str) -> bool:
        for pat in stop_patterns:
            if regex.match(s, pat):
                return True
        return False

    return stops_on


ArrowParse = Fn[[str], Seq[ParseStep]]


class AddressComponent(NamedTuple):
    compiled_pattern: Pattern[str]
    label: str
    cont: Opt[AddressComponent] = None
    optional: bool = False
    stops_on: Fn[[str], bool] = lambda s: False

    def arrow_parse(self) -> ArrowParse:
        def ap(s: str) -> Seq[ParseStep]:
            # print(s)
            if self.stops_on(s):
                # print("stopped")
                return []

            m = regex.match(s, self.compiled_pattern)

            if m is None:
                if self.optional:
                    return []
                raise ParseError(s, self.label)
            p_r = ParseStep(value=m, label=self.label)
            # print(p_r)
            return [p_r]

        return ap

    def then(self, cont: AddressComponent) -> AddressComponent:
        return self._replace(cont=cont)


def __open__(path: str) -> List[str]:
    return open(path, "r").read().upper().split()


st_suffices: List[str] = __open__("st_suffices.txt")

st_suffix_R = re.compile(regex.or_(st_suffices))

st_NESWs: List[str] = ["NE", "NW", "SE", "SW", "N", "S", "E", "W"]
st_NESW_R = re.compile(regex.or_(st_NESWs))

us_states: List[str] = __open__("us_states.txt")

us_state_R = re.compile(regex.or_(us_states))

unit_types: List[str] = __open__("unit_types.txt")

unit_R = re.compile(regex.or_(unit_types))
unit_identifier_R = re.compile(r"\#?\s*(\d+[A-Z]?|[A-Z]\d*)")

zip_code_R = re.compile(r"\d{5}")

_HOUSE_NUMBER = AddressComponent(
    label="house_number", compiled_pattern=re.compile(r"[\d/]+")  # 123 1/3 Pine St
).arrow_parse()


def __make_st_name__(
    known_cities: Seq[Pattern[str]] = (),
) -> Fn[[str], Seq[ParseStep]]:
    return AddressComponent(
        label="st_name",
        compiled_pattern=re.compile(r"\w+"),
        stops_on=__make_stops_on__(
            [st_suffix_R, st_NESW_R, unit_R] + list(known_cities)
        ),
    ).arrow_parse()


# _ST_NAME = __make_st_name__()


def __chomp_unit__(words: Seq[str]) -> Seq[ParseStep]:
    assert len(words) == 2
    unit: Opt[str] = None
    if words[0] == "#":
        unit = "APT"
    else:
        unit = regex.match(words[0], unit_R)
    identifier = regex.match(words[1], unit_identifier_R)
    # print("uunit", unit, identifier)
    if (unit is None) or (identifier is None):
        # print("unit failed")
        return []
    result = ParseStep(value="{0} {1}".format(unit, identifier), label="unit")
    return [result]


_ST_NESW = AddressComponent(label="st_NESW", compiled_pattern=st_NESW_R).arrow_parse()

_ST_SUFFIX = AddressComponent(
    label="st_suffix", compiled_pattern=st_suffix_R
).arrow_parse()

_US_STATE = AddressComponent(
    label="us_state", compiled_pattern=us_state_R
).arrow_parse()

_ZIP_CODE = AddressComponent(
    label="zip_code", compiled_pattern=zip_code_R
).arrow_parse()

address_midpoint_R = re.compile(regex.or_(st_suffices + st_NESWs + unit_types))


def str_to_opt(s: Opt[str]) -> Opt[str]:
    if s is None:
        return None
    if not s.split():
        return None
    return s


def city_repl(s: Match[str]) -> str:
    return " " + s.group(0).strip().replace(" ", "_") + " "


Zip = Zipper[str, str]


class Fns_Of_Parser(Fns_Of):
    @staticmethod
    def city(s: str) -> Seq[ParseStep]:
        raise NotImplementedError

    @staticmethod
    def st_name(s: str) -> Seq[ParseStep]:
        raise NotImplementedError


class Parser:

    """
    A callable address parser.
    In general, prefer using the Hammer class instead of calling the parser directly.
    Parser does not correct typos or auto-infer street suffices or dirrectionals.
    Parser also has the limitation that if the address's city is not in known_cities,
    it will need some kind of identifier to separate the street name and the city name (such as st_suffix, st_NESW or a unit.)

        p = Parser(known_cities="Houston Dallas".split())

    'p' WILL parse the following addresses:

        "123 Straight Houston TX"        # no identifier bewteen street and city (BUT a known city)

        "123 8th Ave NE Ste A Dallas TX" # nothing to see here, normal address

        "123 Dallas Rd Houston TX"       # the street would be recognized as a city (BUT fortunately there is an identifier bewteen the street and city)



    ... but will NOT parse these:

        "123 Straight Houuston TX" #typo

        "123 Straight Austin TX"   #(1) unknown city and (2) no identifier bewteen street and city

        "123 Dallas Houston TX"    # # the street is recognized as a city (and unfortunately there is not an identifier bewteen the street and city)
    """

    __Apply__ = Apply
    __ex_types__ = {"ex_types": tuple([ParseError])}
    __fns__: Fns_Of_Parser
    blank_parse: Opt[Parser]
    required: Set[str] = set(address.HARD_COMPONENTS)
    optional: Set[str] = set(address.SOFT_COMPONENTS)
    known_cities: List[str] = []
    known_cities_R: Opt[Pattern[str]] = None

    def __init__(self, known_cities: Seq[str] = ()):

        known_cities = list(filter(None, known_cities))
        if known_cities:
            self.blank_parse = Parser(known_cities=[])
        else:
            self.blank_parse = None
        normalized_cities = [self.__tokenize__(city) for city in known_cities]
        normalized_cities_B = [w.replace(" ", r"[\s_]") for w in normalized_cities]
        self.known_cities_R = re.compile(regex.or_(normalized_cities_B))
        self.known_cities = known_cities
        city_A = AddressComponent(
            label="city",
            compiled_pattern=re.compile(regex.or_(normalized_cities_B + [r"\w+"])),
            stops_on=__make_stops_on__([us_state_R, re.compile(r"\d+")]),
        ).arrow_parse()

        if self.known_cities_R:
            st_name = __make_st_name__([self.known_cities_R])
        else:
            st_name = __make_st_name__()

        class __Fns_Of_Parser__(Fns_Of_Parser):
            @staticmethod
            def city(s: str) -> Seq[ParseStep]:
                return [
                    ParseStep(value=pr.value.replace("_", " "), label=pr.label)
                    for pr in city_A(s)
                ]

            @staticmethod
            def st_name(s: str) -> Seq[ParseStep]:
                return st_name(s)

        self.__fns__ = __Fns_Of_Parser__()

    @property
    def city(self) -> Fn[[str], Seq[ParseStep]]:
        return self.__fns__.city

    @property
    def st_name(self) -> Fn[[str], Seq[ParseStep]]:
        return self.__fns__.st_name

    def __tokenize__(self, s: str) -> str:
        s = s.replace(",", " ")
        # s = re.sub(p,s," ")
        s = regex.normalize_whitespace(regex.remove_punc(s).upper())
        s = s.replace("#", "APT ")
        s = s.replace("APT APT", "APT")
        if self.known_cities_R:
            s = re.sub(self.known_cities_R, city_repl, s)
        return s

    @staticmethod
    def __city_orig__(s: str) -> str:
        s = " ".join([regex.titleize(word) for word in s.split("_")])
        # print(s)
        return s

    def __hn_nesw__(self) -> List[Fn[[Zipper[str, ParseStep]], Zipper[str, ParseStep]]]:
        Apply = Parser.__Apply__
        p = Parser.__ex_types__
        return [
            Apply.consume_with(_HOUSE_NUMBER, **p),
            Apply.consume_with(_ST_NESW, **p),
            Apply.takewhile(self.st_name, False, **p),
            Apply.takewhile(_ST_SUFFIX, False, **p),
            Apply.consume_with(_ST_NESW, **p),
        ]

    def __collect_results__(
        self, _s: str, results: Iter[ParseStep], checked: bool
    ) -> RawAddress:
        d: Dict[str, List[str]] = {
            "house_number": [],
            "st_name": [],
            "st_suffix": [],
            "st_NESW": [],
            "unit": [],
            "city": [],
            "us_state": [],
            "zip_code": [],
        }

        for p_r in results:
            if p_r.label != "junk":
                d[p_r.label] += [p_r.value]

        # TODO perform S NW AVE bvld sanity checks right here
        if checked:
            for req in self.required:
                if not d[req]:
                    # msg_b = """\nIf you want to allow this, try passing creating the Parser with the optional kwarg, i.e \n p =  Parser(optional=[..., "{req}"])
                    # """.format(req=req)
                    raise ParseError(_s, "Could not identify " + req)

        d["unit"] = [n.replace("#", "") for n in d["unit"]]
        str_d: Dict[str, Opt[str]] = {
            field: " ".join(values) for field, values in d.items()
        }
        for opt in Parser.optional:
            str_d[opt] = str_to_opt(str_d[opt])
        str_d["is_raw"] = "true"
        str_d["orig"] = _s
        a = Address.from_dict(str_d)
        assert isinstance(a, RawAddress)
        return a

    def __call__(self, _s: str, checked: bool = True) -> RawAddress:
        Apply = Parser.__Apply__
        if self.blank_parse is not None:
            try:
                return self.blank_parse(_s, checked=checked)
            except:
                pass
        s = self.__tokenize__(_s)
        p = Parser.__ex_types__
        unit: Fn[[Zipper[str, ParseStep]], Zipper[str, ParseStep]] = lambda z: z
        zip_code: Fn[[Zipper[str, ParseStep]], Zipper[str, ParseStep]] = lambda z: z
        if regex.match(s, unit_R):
            unit = Apply.chomp_n(2, __chomp_unit__, **p)
        data = s.split()
        if data and regex.match(data[-1], zip_code_R):
            zip_code = Apply.consume_with(_ZIP_CODE, **p)
        # TODO make Zipper.takewhile ignore exceptions after 1 consumed???
        funcs: List[Fn[[Zipper[str, ParseStep]], Zipper[str, ParseStep]]] = [
            *self.__hn_nesw__(),
            unit,
            Apply.takewhile(self.city),
            Apply.consume_with(_US_STATE),
            zip_code,
        ]
        try:

            f: Fn[[Zipper[str, ParseStep]], Zipper[str, ParseStep]] = Apply.reduce(
                funcs
            )
            l: GenericInput[str] = GenericInput(data=data)
            z: Zipper[str, ParseStep] = f(Zipper(l))

        except EndOfInputError as e:
            raise EndOfAddressError(_s, "unknown")

        except ParseError as e:
            raise ParseError(_s, e.reason)

        return self.__collect_results__(_s, z.results, checked)

    def parse_row(self, row: Iter[str]) -> RawAddress:

        unit: Fn[[Zipper[str, ParseStep]], Zipper[str, ParseStep]] = lambda z: z
        # zip_code: Fn[[Zipper[str,ParseStep]], Zipper[str,ParseStep]] = lambda z: z
        row = [self.__tokenize__(s) for s in row]
        for cell in row:
            if regex.match(cell, unit_R):
                unit = Apply.chomp_n(2, __chomp_unit__)
                break
        leftovers = [cell.split() for cell in row]
        _z: Zipper[Seq[str], ParseStep] = Zipper(
            leftover=GenericInput(leftovers), results=[]
        )

        funcs: List[Fn[[Zipper[str, ParseStep]], Zipper[str, ParseStep]]] = [
            *self.__hn_nesw__(),
            unit,
            Apply.takewhile(self.city),
            Apply.consume_with(_US_STATE),
            Apply.consume_with(_ZIP_CODE),
        ]

        z = zipper_x(_z, funcs)

        results = list(z.results)

        # print(results)

        return self.__collect_results__("\t".join(row), results, False)


def smart_batch(
    p: Parser,
    adds: Iter[str],
    report_error: Fn[[ParseError, str], None] = lambda e, s: None,
) -> Iter[RawAddress]:
    """
    This function takes an iter of address strings and tries to repair dirty addresses by using the city information from clean ones.
    For example: "123 Main, Springfield OH 12123" will be correctly parsed iff 'SPRINGFIELD' is a city of another address.
    The 'report_error' callback is called on all address strings that cannot be repaired
    (other than 'report_error', all ParseErrors are ignored)
    """
    errs: List[str] = []
    cities: Set[str] = set([])
    pre = 0
    for add in adds:
        try:
            a = p(add)
            cities.add(a.city)
            pre += 1
            # if pre % 1000 == 0:
            # print(str(pre // 1000) + "k good so far!")
            yield a
        except EndOfInputError:
            errs.append(add)
        except ParseError:
            errs.append(add)

    # print("good:", pre)
    # print(cities)
    p = Parser(known_cities=p.known_cities + list(cities))
    fixed = 0
    for add in errs:
        try:
            a = p(add)
            fixed += 1
            yield a
        except ParseError as e:
            report_error(e, add)
    # print("fixed:", fixed)


__difficult_addresses__ = [
    "000  Plymouth Rd Trlr 113  Ford MI 48000",
    "0 Joy Rd Trlr 105  Red MI 48000",
    "0  Stoepel St #0  Detroit MI 48000",
    "0 W Boston Blvd # 7  Detroit MI 48000",
]