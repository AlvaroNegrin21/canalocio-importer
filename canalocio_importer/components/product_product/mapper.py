import logging

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

    @mapping
    def map_record(self, record):
        """
        Main mapping method to transform source record (CSV row dict)
        into Odoo product.template values.
        Handles None values returned by the CSV reader for empty fields.
        """
        processed_record = {}
        for k, v in record.items():
            if k and isinstance(k, str):
                if v is None:
                    processed_record[k] = ""
                else:
                    processed_record[k] = v

        record = processed_record

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
                "Mapper %s: Could not find linked import.recordset for backend %s (ID: %s) and import type 'product_product_canal'.",
                self._name,
                backend_record.display_name,
                backend_record.id,
            )
            raise UserError(
                "Import recordset configuration not found based on backend and type key."
            )

        source_config_id = recordset_record.source_id
        source_config = self.env["import.source.csv"].browse(source_config_id)

        if (
            not source_config
            or not source_config.exists()
            or not source_config._name == "import.source.csv"
        ):
            _logger.error(
                "Mapper %s: Retrieved source_config is not import.source.csv or is missing after browsing.",
                self._name,
            )
            raise UserError(
                "Import source configuration found is not of the expected type."
            )

        parse_float_method = getattr(source_config, "_parse_float", None)
        fetch_image_b64_method = getattr(source_config, "_fetch_image_b64", None)

        if not parse_float_method or not fetch_image_b64_method:
            _logger.warning(
                "Mapper %s: Required methods (_parse_float or _fetch_image_b64) not found on source_config %s.",
                self._name,
                source_config.display_name,
            )

        barcode = _safe_get_string(record, "ean13")

        if not barcode:
            _logger.warning(
                "Config ID %s: Row skipped - EAN13 is empty. Raw data: %s",
                source_config.id,
                record,
            )
            return None
        if not barcode.isdigit():
            _logger.warning(
                "Config ID %s: Row skipped - EAN13 contains non-digits. Value: '%s'. Raw data: %s",
                source_config.id,
                barcode,
                record,
            )
            return None

        if len(barcode) not in [8, 12, 13]:
            _logger.warning(
                "Config ID %s: Warning - EAN13 has unusual length (%s). Value: '%s'. Raw data: %s",
                source_config.id,
                len(barcode),
                barcode,
                record,
            )

        title = _safe_get_string(record, "titulo", f"Producto {barcode}")

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

        image_url = _safe_get_string(record, "caratula")
        image_b64 = False
        if image_url and fetch_image_b64_method:
            _logger.info(
                "Mapper %s (Config ID %s): Image URL found. Attempting to fetch image from URL: %s",
                self._name,
                source_config.id,
                image_url,
            )
            try:
                image_b64 = fetch_image_b64_method(image_url)
                _logger.info(
                    "Mapper %s (Config ID %s): Image fetch result: %s",
                    self._name,
                    source_config.id,
                    "Success (Base64 data obtained)"
                    if image_b64
                    else "Failed or No data",
                )
            except Exception as e:
                _logger.error(
                    "Mapper %s (Config ID %s): Failed to fetch image from URL %s for barcode %s: %s",
                    self._name,
                    source_config.id,
                    image_url,
                    barcode,
                    e,
                    exc_info=True,
                )
                image_b64 = False

        elif not image_url:
            _logger.info(
                "Mapper %s (Config ID %s): No image URL provided for barcode %s.",
                self._name,
                source_config.id,
                barcode,
            )
        elif not fetch_image_b64_method:
            _logger.warning(
                "Mapper %s (Config ID %s): Image URL provided but _fetch_image_b64 method is missing on source_config.",
                self._name,
                source_config.id,
            )

        html_content = ""
        disponibilidad = _safe_get_string(record, "disponibilidad")
        if disponibilidad:
            html_content += (
                f"<p><label>Fecha distribución:</label> {disponibilidad}</p>"
            )
        distribuidor = _safe_get_string(record, "distribuidor")
        if distribuidor:
            html_content += f"<p><label>Distribuidor:</label> {distribuidor}</p>"
        sinopsis = _safe_get_string(record, "sinopsis")
        if sinopsis:
            html_content += f"<p><label>Info:</label> {sinopsis}</p>"
        director = _safe_get_string(record, "pelicula director")
        if director:
            html_content += f"<p><label>Directores:</label> {director}</p>"
        actores = _safe_get_string(record, "pelicula actores")
        if actores:
            html_content += f"<p><label>Actores:</label> {actores}</p>"
        duracion = _safe_get_string(record, "pelicula duracion")
        if duracion:
            html_content += f"<p><label>Duración:</label> {duracion}</p>"
        audio = _safe_get_string(record, "pelicula audio")
        if audio:
            html_content += f"<p><label>Audio:</label> {audio}</p>"
        subtitulos = _safe_get_string(record, "pelicula subtitulos")
        if subtitulos:
            html_content += f"<p><label>Subtítulos:</label> {subtitulos}</p>"
        clasificacion = _safe_get_string(record, "pelicula clasificacion")
        if clasificacion:
            html_content += f"<p><label>Clasificación:</label> {clasificacion}</p>"

        genre_names = []
        for i in range(1, 6):
            genre_name = _safe_get_string(record, f"genero_{i}")
            if genre_name:
                genre_names.append(genre_name)
        if genre_names:
            html_content += f"<p><label>Género:</label> {', '.join(genre_names)}</p>"

        description_sale = _safe_get_string(record, "sinopsis")
        description = html_content

        tag_names = []
        for i in range(1, 7):
            tag_column = f"tag_{i}"
            tag_name = _safe_get_string(record, tag_column)
            if tag_name:
                tag_names.append(tag_name)

        cache_key = f"tags_recordset_{recordset_record.id}"
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
            source_config.id,
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
                        "Mapper %s (Config ID %s): Tag '%s' found in cache (ID: %s).",
                        self._name,
                        source_config.id,
                        tag_name,
                        tag_id,
                    )
                    tag_ids.append(tag_id)
            else:
                tag = ProductTag.search([("name", "=ilike", tag_name)], limit=1)
                if tag:
                    _logger.debug(
                        "Mapper %s (Config ID %s): Tag '%s' found in DB (ID: %s).",
                        self._name,
                        source_config.id,
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
                            source_config.id,
                            tag_name,
                        )
                        new_tag = ProductTag.create({"name": tag_name})
                        _logger.info(
                            f"Config ID {source_config.id}: Created new tag '{tag_name}' (ID: {new_tag.id})"
                        )
                        current_tag_cache[tag_name_lower] = new_tag.id
                        tag_ids.append(new_tag.id)
                    except Exception as e:
                        _logger.error(
                            f"Config ID {source_config.id}: Failed to create tag '{tag_name}' for barcode {barcode}: {e}",
                            exc_info=True,
                        )
                        current_tag_cache[tag_name_lower] = None

        unique_tag_ids = list(set(tag_ids))
        tag_m2m_command = [(6, 0, unique_tag_ids)]

        odoo_values = {
            "name": title,
            "barcode": barcode,
            "list_price": pvp,
            "standard_price": pvd,
            "weight": weight,
            "sale_ok": is_available,
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
                "Mapper %s (Config ID %s): 'taxes_id' key found in mapped values before return. Removing it.",
                self._name,
                source_config.id,
            )
            del odoo_values["taxes_id"]

        return odoo_values
