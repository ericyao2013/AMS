#!/usr/bin/env python
# coding: utf-8

from numpy import pi
from ams.structures import get_base_class, get_namedtuple_from_dict

RPY = get_namedtuple_from_dict("CONST", {
    "PI2": 2.0 * pi
})

template = {
    "roll": 0.0,
    "pitch": 0.0,
    "yaw": 0.0,
}

schema = {
    "roll": {
        "type": "number",
        "required": True,
        "nullable": True,
        "min": 0.0,
        "max": RPY.PI2
    },
    "pitch": {
        "type": "number",
        "required": True,
        "nullable": True,
        "min": 0.0,
        "max": RPY.PI2
    },
    "yaw": {
        "type": "number",
        "required": True,
        "nullable": True,
        "min": 0.0,
        "max": RPY.PI2
    }
}


class Rpy(get_base_class(template, schema)):
    pass
