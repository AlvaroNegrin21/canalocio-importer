import logging
from urllib.parse import urlparse

import requests

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.connector_importer.utils.import_utils import (
    CSVReader,
    guess_csv_metadata,
)

from ..utils.url_constants import *

_logger = logging.getLogger(__name__)


def is_valid_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False


class HTTPCSVReader(CSVReader):
    """CSVReader with support for HTTP URLs."""

    def __init__(self, filepath=None, chunk_size=8192, **kwargs):
        specified_encoding = kwargs.get("encoding")
        _logger.info("HTTPCSVReader: Initial kwargs encoding: %s", specified_encoding)

        downloaded_content = None
        final_kwargs = kwargs.copy()

        if filepath and is_valid_url(filepath):
            _logger.info("HTTPCSVReader: Fetching CSV from URL: %s", filepath)
            response = None
            downloaded_content = b""

            try:
                with requests.get(
                    filepath,
                    stream=True,
                    timeout=REQUESTS_TIMEOUT,
                    headers={"Accept-Encoding": "gzip, deflate"},
                ) as response:
                    response.raise_for_status()

                    for chunk in response.iter_content(chunk_size=chunk_size):
                        downloaded_content += chunk

                    if not downloaded_content:
                        _logger.error(
                            "HTTPCSVReader: Downloaded content is empty from %s",
                            filepath,
                        )
                        raise UserError(
                            _("The HTTP response from %s is empty.") % filepath
                        )

                    _logger.info(
                        "HTTPCSVReader: Downloaded %s bytes.", len(downloaded_content)
                    )
                    try:
                        meta = guess_csv_metadata(downloaded_content)
                        _logger.info("HTTPCSVReader: Guessed metadata: %s", meta)
                        final_kwargs.update(
                            {
                                k: v
                                for k, v in meta.items()
                                if k in ("delimiter", "quotechar")
                            }
                        )

                        _logger.info(
                            "HTTPCSVReader: Encoding passed to super: %s",
                            final_kwargs.get("encoding", "Default/None"),
                        )

                    except Exception as meta_err:
                        _logger.error(
                            "HTTPCSVReader: Error guessing metadata: %s", meta_err
                        )
                        raise meta_err

                    final_kwargs["filedata"] = downloaded_content
                    filepath = None

            except requests.Timeout:
                _logger.error(
                    "HTTPCSVReader: Timeout while fetching CSV from %s", filepath
                )
                raise UserError(
                    _("Timeout while fetching CSV from %s. Please try again later.")
                    % filepath
                )
            except requests.RequestException as e:
                _logger.error(
                    "HTTPCSVReader: Error fetching CSV from %s: %s", filepath, e
                )
                raise UserError(_("Error fetching CSV from %s: %s") % (filepath, e))
            except Exception as e:
                _logger.exception(
                    "HTTPCSVReader: Unexpected error during HTTP fetch for %s", filepath
                )
                raise UserError(
                    _("Unexpected error processing CSV from %s: %s") % (filepath, e)
                )
            finally:
                if response:
                    response.close()

        super().__init__(filepath=filepath, **final_kwargs)
