import unittest
from unittest.mock import patch

from local_debugger import import_hok_module
from web import database


ZDB = import_hok_module("zdb")


class DatabaseConfigurationTests(unittest.TestCase):
    def test_missing_bot_dsn_never_opens_an_implicit_local_connection(self):
        with patch.object(ZDB, "postgres_dsn", ""), patch("psycopg.connect") as connect:
            with self.assertRaisesRegex(ValueError, "HOK_DATABASE_DSN"):
                ZDB.ping()
        connect.assert_not_called()

    def test_missing_web_dsn_never_opens_an_implicit_local_connection(self):
        with patch("psycopg.connect") as connect:
            with self.assertRaisesRegex(ValueError, "HOK_DATABASE_DSN"):
                database.ping("")
        connect.assert_not_called()
