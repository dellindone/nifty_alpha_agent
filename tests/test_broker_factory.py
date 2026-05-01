import pytest

from brokers.factory import BrokerFactory
from brokers.fyers.adapter import FyersAdapter
from brokers.groww.adapter import GrowwAdapter


def test_create_fyers():
    assert isinstance(BrokerFactory.create("fyers"), FyersAdapter)


def test_create_groww():
    assert isinstance(BrokerFactory.create("groww"), GrowwAdapter)


def test_create_unknown():
    with pytest.raises(ValueError):
        BrokerFactory.create("unknown")


def test_create_case_insensitive():
    assert isinstance(BrokerFactory.create("FYERS"), FyersAdapter)
