
def all_tests():
    from .address import test as address_test
    from .__zipper__ import test as zipper_test
    from .parsing import test as parsing_test
    from .fuzzy_string import test as fuzzy_string_test

    address_test()
    zipper_test()
    parsing_test()
    fuzzy_string_test()

all_tests()