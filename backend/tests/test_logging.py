"""The application's own log lines must actually reach the console.

Found in real conditions: `docker compose logs api` showed uvicorn's access
lines and "Application startup complete", but never "Extraction provider
ready", and never the line written after each extraction. Under uvicorn the
root logger stays at WARNING with no handler, so every INFO from this codebase
was dropped -- including the only record of which provider answered, how many
records it returned and how long it took.
"""

import logging

from app.logging_setup import APP_LOGGER, configure_logging


class TestApplicationLogsAreVisible:
    def test_an_info_line_from_the_app_namespace_is_emitted(self, capsys):
        configure_logging("INFO")

        logging.getLogger("app.providers.openai").info("Extraction succeeded: records=8")

        assert "Extraction succeeded: records=8" in capsys.readouterr().err

    def test_the_level_is_configurable(self, capsys):
        configure_logging("WARNING")

        logging.getLogger("app.main").info("this one is below the configured level")

        assert "below the configured level" not in capsys.readouterr().err

    def test_calling_it_twice_does_not_duplicate_every_line(self, capsys):
        configure_logging("INFO")
        configure_logging("INFO")

        logging.getLogger("app.main").info("once")

        assert capsys.readouterr().err.count("once") == 1

    def test_the_configured_level_reaches_the_namespace(self):
        configure_logging("INFO")
        assert logging.getLogger(APP_LOGGER).isEnabledFor(logging.INFO)
