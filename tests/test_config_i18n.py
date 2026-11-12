from pipeline import config


def test_regions_valid():
    regions = config.load_regions()
    r = regions[0]
    assert r["id"] == "be-namur" and abs(r["lat"] - 50.47) < 1e-9 and abs(r["lon"] - 4.87) < 1e-9
    assert r["timezone"] == "Europe/Brussels"


def test_weights_match_spec():
    m = config.load_scoring()["modes"]
    assert m["comfort"]["weights"] == {"temperature": 30, "moisture": 15, "wetness": 25, "rain": 10, "wind": 10, "sun": 10}
    assert m["performance"]["weights"] == {"temperature": 25, "moisture": 25, "wetness": 30, "rain": 10, "wind": 5, "sun": 5}
    assert m["comfort"]["temp_ideal_c"] == [8, 18] and m["performance"]["temp_ideal_c"] == [2, 12]


def _flat(d, p=""):
    out = set()
    for k, v in d.items():
        out |= _flat(v, p + k + ".") if isinstance(v, dict) else {p + k}
    return out


def test_languages_have_same_keys():
    i = config.load_i18n()
    assert _flat(i["en"]) == _flat(i["fr"])


def test_all_driver_keys_translated():
    names = {"temperature_cold", "temperature_warm", "moisture", "wetness", "rain", "wind_calm", "wind_strong", "sun",
             "cap_active_rain", "cap_very_wet"}
    for lang in config.load_i18n().values():
        assert names <= set(lang["drivers"])
