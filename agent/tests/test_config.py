import pytest

from sentineleye_agent.config import ConfigError, load_config, read_env_file

TOKEN = "se_0123456789abcdef_" + "A" * 43


def env(**overrides):
    base = {
        "SENTINELEYE_URL": "https://monitor.example.com",
        "SENTINELEYE_TOKEN": TOKEN,
        "SENTINELEYE_SERVER_ID": "3",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def test_valid_configuration():
    config = load_config(env(SENTINELEYE_INTERVAL="60"))
    assert config.server_id == 3
    assert config.interval_seconds == 60
    assert config.metrics_url == "https://monitor.example.com/api/agent/metrics"


def test_defaults():
    config = load_config(env())
    assert config.interval_seconds == 30
    assert config.max_retries == 4
    assert config.disk_path == "/"


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"SENTINELEYE_URL": None}, "SENTINELEYE_URL"),
        ({"SENTINELEYE_URL": "monitor.example.com"}, "SENTINELEYE_URL"),
        ({"SENTINELEYE_TOKEN": None}, "SENTINELEYE_TOKEN"),
        ({"SENTINELEYE_TOKEN": "se_short_token"}, "SENTINELEYE_TOKEN"),
        ({"SENTINELEYE_SERVER_ID": "abc"}, "SENTINELEYE_SERVER_ID"),
        ({"SENTINELEYE_SERVER_ID": "0"}, "SENTINELEYE_SERVER_ID"),
        ({"SENTINELEYE_INTERVAL": "2"}, "SENTINELEYE_INTERVAL"),
        ({"SENTINELEYE_INTERVAL": "soon"}, "SENTINELEYE_INTERVAL"),
        ({"SENTINELEYE_CA_BUNDLE": "/nope/ca.pem"}, "SENTINELEYE_CA_BUNDLE"),
    ],
)
def test_invalid_configuration(overrides, message):
    with pytest.raises(ConfigError, match=message):
        load_config(env(**overrides))


def test_plain_http_is_refused_for_remote_hosts():
    with pytest.raises(ConfigError, match="plain HTTP"):
        load_config(env(SENTINELEYE_URL="http://monitor.example.com"))
    assert load_config(env(SENTINELEYE_URL="http://monitor.example.com", SENTINELEYE_ALLOW_HTTP="true"))
    assert load_config(env(SENTINELEYE_URL="http://localhost:8000"))


def test_config_file_and_environment_precedence(tmp_path):
    path = tmp_path / "agent.env"
    path.write_text(
        "# comment\n"
        "SENTINELEYE_URL=https://from-file.example.com\n"
        f'SENTINELEYE_TOKEN="{TOKEN}"\n'
        "SENTINELEYE_SERVER_ID=9\n"
    )
    assert read_env_file(path)["SENTINELEYE_TOKEN"] == TOKEN
    config = load_config({"SENTINELEYE_SERVER_ID": "4"}, config_file=str(path))
    assert config.backend_url == "https://from-file.example.com"
    assert config.server_id == 4  # environment wins over the file


def test_malformed_config_file(tmp_path):
    path = tmp_path / "agent.env"
    path.write_text("this line has no equals sign\n")
    with pytest.raises(ConfigError, match="KEY=VALUE"):
        read_env_file(path)


def test_token_never_appears_in_repr():
    assert TOKEN not in repr(load_config(env()))
