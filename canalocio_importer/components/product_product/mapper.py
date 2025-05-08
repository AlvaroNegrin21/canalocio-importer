import logging

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping

_logger = logging.getLogger(__name__)


def _safe_get_string(record, key, default=""):
    """Get value from record, ensuring it's a string, and strip whitespace."""
    value = record.get(key)
    if value is None:
        return default
    return str(value).strip()


class ProductProductCanalMapper(Component):
    _name = "product.product.canal.mapper"
    _inherit = "importer.mapper.dynamic"
    _apply_on = "product.template"
    _mapper_usage = "importer.mapper"

    def _preprocess_record(self, record):
        """Replace None values with empty strings in the record."""
        processed_record = {}
        for k, v in record.items():
            if k and isinstance(k, str):
                processed_record[k] = "" if v is None else v
        return processed_record

    def _get_source_config(self):
        """Find and validate the associated import.source.csv configuration."""
        backend_record = self.collection
        recordset_record = self.env["import.recordset"].search(
            [
                ("backend_id", "=", backend_record.id),
                ("import_type_id.key", "=", "product_product_canal"),
            ],
            limit=1,
        )

        if not recordset_record:
            _logger.error(
                "Mapper %s: Could not find linked import.recordset for backend "
                "%s (ID: %s) and import type 'product_product_canal'.",
                self._name,
                backend_record.display_name,
                backend_record.id,
            )
            raise UserError(
                _(
                    "Import recordset configuration not found based on backend "
                    "and type key."
                )
            )

        source_config_id = recordset_record.source_id
        source_config = self.env["import.source.csv"].browse(source_config_id)

        if (
            not source_config
            or not source_config.exists()
            or not source_config._name == "import.source.csv"
        ):
            _logger.error(
                "Mapper %s: Retrieved source_config is not import.source.csv or "
                "is missing after browsing.",
                self._name,
            )
            raise UserError(
                _("Import source configuration found is not of the expected type.")
            )

        return source_config, recordset_record

    def _validate_barcode(self, record, source_config_id):
        """Validate the EAN13 barcode and return it, or None if invalid."""
        barcode = _safe_get_string(record, "ean13")

        if not barcode:
            _logger.warning(
                "Config ID %s: Row skipped - EAN13 is empty. Raw data: %s",
                source_config_id,
                record,
            )
            return None
        if not barcode.isdigit():
            _logger.warning(
                "Config ID %s: Row skipped - EAN13 contains non-digits. "
                "Value: '%s'. Raw data: %s",
                source_config_id,
                barcode,
                record,
            )
            return None

        if len(barcode) not in [8, 12, 13]:
            _logger.warning(
                "Config ID %s: Warning - EAN13 has unusual length (%s). "
                "Value: '%s'. Raw data: %s",
                source_config_id,
                len(barcode),
                barcode,
                record,
            )

        return barcode

    def _map_basic_fields(self, record, parse_float_method, source_config):
        """Map basic fields like title, prices, weight, and availability."""
        title = _safe_get_string(
            record, "titulo", f"Producto {_safe_get_string(record, 'ean13')}"
        )

        pvp = (
            parse_float_method(_safe_get_string(record, "pvp"))
            if parse_float_method
            else 0.0
        )
        pvd = (
            parse_float_method(_safe_get_string(record, "pvd"))
            if parse_float_method
            else 0.0
        )
        weight = (
            parse_float_method(_safe_get_string(record, "peso"))
            if parse_float_method
            else 0.0
        )

        is_available = (
            _safe_get_string(record, "estado").lower()
            == source_config.available_state.lower()
        )

        return {
            "name": title,
            "list_price": pvp,
            "standard_price": pvd,
            "weight": weight,
            "sale_ok": is_available,
        }

    def _fetch_image(self, record, source_config_id, barcode, fetch_image_b64_method):
        """Fetch the product image from a URL if available."""
        image_url = _safe_get_string(record, "caratula")
        image_b64 = False

        if not image_url:
            _logger.info(
                "Mapper %s (Config ID %s): No image URL provided for barcode %s.",
                self._name,
                source_config_id,
                barcode,
            )
            return False

        if not fetch_image_b64_method:
            _logger.warning(
                "Mapper %s (Config ID %s): Image URL provided but "
                "_fetch_image_b64 method is missing on source_config.",
                self._name,
                source_config_id,
            )
            return False

        _logger.info(
            "Mapper %s (Config ID %s): Image URL found. Attempting to fetch "
            "image from URL: %s",
            self._name,
            source_config_id,
            image_url,
        )
        try:
            image_b64 = fetch_image_b64_method(image_url)
            _logger.info(
                "Mapper %s (Config ID %s): Image fetch result: %s",
                self._name,
                source_config_id,
                "Success (Base64 data obtained)" if image_b64 else "Failed or No data",
            )
        except Exception as e:
            _logger.error(
                "Mapper %s (Config ID %s): Failed to fetch image from URL %s "
                "for barcode %s: %s",
                self._name,
                source_config_id,
                image_url,
                barcode,
                e,
                exc_info=True,
            )
            image_b64 = False
        return image_b64

    def _build_html_description(self, record):
        """Build the HTML description from various record fields."""
        html_content = ""

        fields_to_include = {
            "disponibilidad": "Fecha distribución",
            "distribuidor": "Distribuidor",
            "sinopsis": "Info",
            "pelicula director": "Directores",
            "pelicula actores": "Actores",
            "pelicula duracion": "Duración",
            "pelicula audio": "Audio",
            "pelicula subtitulos": "Subtítulos",
            "pelicula clasificacion": "Clasificación",
        }

        for key, label in fields_to_include.items():
            value = _safe_get_string(record, key)
            if value:
                html_content += f"<p><label>{label}:</label> {value}</p>"

        genre_names = []
        for i in range(1, 6):
            genre_name = _safe_get_string(record, f"genero_{i}")
            if genre_name:
                genre_names.append(genre_name)
        if genre_names:
            html_content += f"<p><label>Género:</label> {', '.join(genre_names)}</p>"

        return html_content

    def _process_tags(self, record, recordset_record_id, source_config_id):
        """Process tags from record, using/creating records with caching."""
        tag_names = []
        for i in range(1, 7):
            tag_column = f"tag_{i}"
            tag_name = _safe_get_string(record, tag_column)
            if tag_name:
                tag_names.append(tag_name)

        if not tag_names:
            return [(6, 0, [])]

        cache_key = f"tags_recordset_{recordset_record_id}"
        if not hasattr(self, "_tag_cache"):
            self._tag_cache = {}
        if cache_key not in self._tag_cache:
            self._tag_cache[cache_key] = {}

        current_tag_cache = self._tag_cache[cache_key]
        tag_ids = []
        ProductTag = self.env["product.tag"]

        _logger.info(
            "Mapper %s (Config ID %s): Processing tags: %s",
            self._name,
            source_config_id,
            tag_names,
        )

        for tag_name in tag_names:
            if not tag_name:
                continue

            tag_name_lower = tag_name.lower()
            if tag_name_lower in current_tag_cache:
                tag_id = current_tag_cache[tag_name_lower]
                if tag_id:
                    _logger.debug(
                        "Mapper %s (Config ID %s): Tag '%s' found in cache "
                        "(ID: %s).",
                        self._name,
                        source_config_id,
                        tag_name,
                        tag_id,
                    )
                    tag_ids.append(tag_id)
            else:
                tag = ProductTag.search([("name", "=ilike", tag_name)], limit=1)
                if tag:
                    _logger.debug(
                        "Mapper %s (Config ID %s): Tag '%s' found in DB " "(ID: %s).",
                        self._name,
                        source_config_id,
                        tag_name,
                        tag.id,
                    )
                    current_tag_cache[tag_name_lower] = tag.id
                    tag_ids.append(tag.id)
                else:
                    try:
                        _logger.info(
                            "Mapper %s (Config ID %s): Creating new tag '%s'.",
                            self._name,
                            source_config_id,
                            tag_name,
                        )
                        new_tag = ProductTag.create({"name": tag_name})
                        _logger.info(
                            f"Config ID {source_config_id}"
                            f": Created new tag '{tag_name}' "
                            f"(ID: {new_tag.id})"
                        )
                        current_tag_cache[tag_name_lower] = new_tag.id
                        tag_ids.append(new_tag.id)
                    except Exception as e:
                        _logger.error(
                            f"Config ID {source_config_id}"
                            f": Failed to create tag '{tag_name}': {e}",
                            exc_info=True,
                        )
                        current_tag_cache[tag_name_lower] = None

        unique_tag_ids = list(set(tag_ids))
        return [(6, 0, unique_tag_ids)]

    @mapping
    def map_record(self, record):
        """
        Main mapping method to transform source record (CSV row dict)
        into Odoo product.template values.
        Handles None values returned by the CSV reader for empty fields.
        """
        processed_record = self._preprocess_record(record)

        source_config, recordset_record = self._get_source_config()

        parse_float_method = getattr(source_config, "_parse_float", None)
        fetch_image_b64_method = getattr(source_config, "_fetch_image_b64", None)

        barcode = self._validate_barcode(processed_record, source_config.id)
        if not barcode:
            return None

        basic_values = self._map_basic_fields(
            processed_record, parse_float_method, source_config
        )

        image_b64 = self._fetch_image(
            processed_record,
            source_config.id,
            barcode,
            fetch_image_b64_method,
        )

        description = self._build_html_description(processed_record)
        description_sale = _safe_get_string(processed_record, "sinopsis")

        tag_m2m_command = self._process_tags(
            processed_record,
            recordset_record.id,
            source_config.id,
        )

        odoo_values = {
            "name": basic_values["name"],
            "barcode": barcode,
            "list_price": basic_values["list_price"],
            "standard_price": basic_values["standard_price"],
            "weight": basic_values["weight"],
            "sale_ok": basic_values["sale_ok"],
            "detailed_type": "product",
            "categ_id": self.env.ref("product.product_category_all").id,
            "description_sale": description_sale,
            "description": description,
            "product_tag_ids": tag_m2m_command,
        }

        if image_b64:
            odoo_values["image_1920"] = image_b64

        if "taxes_id" in odoo_values:
            _logger.warning(
                "Mapper %s (Config ID %s): 'taxes_id' key found in mapped values "
                "before return. Removing it.",
                self._name,
                source_config.id,
            )
            del odoo_values["taxes_id"]

        return odoo_values
