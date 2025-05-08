import base64
import io
import logging

import requests
from PIL import Image

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..utils.import_utils import HTTPCSVReader, is_valid_url
from ..utils.url_constants import (
    IMAGE_TIMEOUT,
    SECOND_HAND_DEFAULT_CODE,
    SECOND_HAND_SUFFIX,
    STATE_AVAILABLE,
)

_logger = logging.getLogger(__name__)


class CSVSource(models.Model):
    _inherit = "import.source.csv"

    _csv_reader_klass = HTTPCSVReader

    second_hand_suffix = fields.Char(
        default=SECOND_HAND_SUFFIX,
        help="The suffix to append to the original product's barcode to create the "
        "second-hand variant's barcode.",
    )
    second_hand_default_code = fields.Char(
        default=SECOND_HAND_DEFAULT_CODE,
        help="The internal reference to set for the second-hand product variants.",
    )
    available_state = fields.Char(
        default=STATE_AVAILABLE,
        help="The exact text (case-insensitive) in the 'estado' CSV column that "
        "signifies a product is available for sale.",
    )

    source_id_ids = fields.One2many(
        "import.recordset",
        "source_id",
        string="Linked Recordsets",
        readonly=True,
        help="Import Recordsets configured to use this source.",
    )

    @property
    def _config_summary_fields(self):
        _fields = super()._config_summary_fields
        return _fields + [
            "csv_path",
            "second_hand_suffix",
            "second_hand_default_code",
            "available_state",
            "source_id_ids",
        ]

    def _generate_csv_reader(self, reader_args):
        """
        Generates the custom CSV reader.
        The HTTPCSVReader uses the `filepath` argument, which is self.csv_path here.
        """
        if not self.csv_path or not is_valid_url(self.csv_path):
            raise UserError(
                _("CSV Path must be a valid HTTP/HTTPS URL for this source type.")
            )

        res = super()._generate_csv_reader(reader_args)
        if self.csv_path and is_valid_url(self.csv_path) and hasattr(res, "delimiter"):
            self.write(
                {
                    "csv_delimiter": res.delimiter,
                    "csv_quotechar": res.quotechar,
                }
            )
        return res

    def _fetch_image_b64(self, url):
        """Fetches an image from a URL and returns it as base64."""
        if not url or not is_valid_url(url):
            _logger.warning("Cannot fetch image from invalid or empty URL: %s", url)
            return False

        response = None
        try:
            _logger.debug("Fetching image from: %s", url)
            response = requests.get(url, stream=True, timeout=IMAGE_TIMEOUT)
            response.raise_for_status()
            image_data = response.content
            try:
                with Image.open(io.BytesIO(image_data)) as img:
                    img.verify()

                base64_image = base64.b64encode(image_data).decode("utf-8")
                _logger.debug("Image fetched and converted to base64 successfully.")
                return base64_image
            except (OSError, Image.UnidentifiedImageError) as img_err:
                _logger.warning(
                    f"Content from URL {url} is not a valid image. Error: {img_err}"
                )
                return False
            except Exception as img_err:
                _logger.warning(f"Error processing image from URL {url}: {img_err}")
                return False

        except requests.Timeout:
            _logger.warning("Timeout fetching image from %s", url)
            return False
        except requests.RequestException as e:
            _logger.warning("Error fetching image from %s: %s", url, e)
            return False
        except Exception as e:
            _logger.error(
                "Unexpected error fetching image %s: %s", url, e, exc_info=True
            )
            return False
        finally:
            if response:
                response.close()

    def _parse_float(self, value):
        """Parses a string value into a float, handling commas as decimal separators."""
        if not value or not isinstance(value, str):
            return 0.0
        cleaned_value = value.strip().replace(",", ".")
        try:
            return float(cleaned_value)
        except ValueError:
            _logger.warning(
                f'Could not parse float from value: "{value}". Returning 0.0.'
            )
            return 0.0
        except Exception as e:
            _logger.error(
                'Unexpected error parsing float value "%s": %s. Returning 0.0.',
                value,
                e,
                exc_info=True,
            )
            return 0.0
