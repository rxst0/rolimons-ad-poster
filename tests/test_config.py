from dataclasses import asdict

from roliposter.config import Config, config_from_dict, validate_config


def test_auto_accept_defaults_off_in_test_mode():
    aa = config_from_dict({}).auto_accept
    assert aa.enabled is False and aa.mode == "test" and aa.block_projected is True
    assert aa.min_value_gain == 10.0 and aa.min_rap_gain is None and aa.max_per_day == 5


def test_auto_accept_round_trips_and_empty_gain_means_unchecked():
    cfg = config_from_dict({"auto_accept": {"enabled": True, "mode": "LIVE", "min_value_gain": 15,
                                            "min_rap_gain": "", "min_price_gain": 5, "max_per_day": 2}})
    aa = cfg.auto_accept
    assert (aa.enabled, aa.mode, aa.min_value_gain, aa.min_rap_gain, aa.min_price_gain, aa.max_per_day) == \
        (True, "live", 15.0, None, 5.0, 2)
    assert config_from_dict(asdict(cfg)).auto_accept == aa


def test_auto_accept_validation():
    def problems(**aa):
        cfg = Config()
        for key, value in aa.items():
            setattr(cfg.auto_accept, key, value)
        return [e for e in validate_config(cfg) if "uto" in e]

    assert problems() == []
    assert problems(mode="yolo")
    assert problems(max_per_day=500)
    assert problems(min_value_gain=5000)
    assert problems(enabled=True, min_value_gain=None)  # at least one rule needed
