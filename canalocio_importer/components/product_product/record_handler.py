import logging

from odoo.exceptions import UserError
from odoo.fields import Command

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class ProductProductCanalRecordHandler(Component):
    """Interact w/ odoo canal ocio importable product records."""

    _name = "product.product.canal.handler"
    _inherit = "importer.odoorecord.handler"
    _apply_on = "product.template"

    def _get_source_config(self):
        """
        Retrieves the import.source.csv configuration linked via the import.recordset.
        """
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
                "Handler %s: Could not find linked import.recordset for backend %s (ID: %s) and import type 'product_product_canal'.",
                self._name,
                backend_record.display_name,
                backend_record.id,
            )
            raise UserError(
                "Import recordset configuration not accessible based on backend and type key."
            )

        source_id_val = recordset_record["source_id"]

        if not source_id_val:
            _logger.error(
                "Handler %s: Found recordset %s (ID: %s), but its source_id field is not set.",
                self._name,
                recordset_record.name,
                recordset_record.id,
            )
            raise UserError(
                "Import recordset configuration found has no linked data source."
            )

        source_config = self.env["import.source.csv"].browse(source_id_val)

        if (
            not source_config
            or not source_config.exists()
            or source_config._name != "import.source.csv"
        ):
            _logger.error(
                "Handler %s: Retrieved source_config is not import.source.csv or is missing after browsing. Found ID: %s, Model: %s",
                self._name,
                source_config.id if source_config.exists() else "None",
                source_config._name if source_config.exists() else "None",
            )
            raise UserError(
                "Import source configuration found is not of the expected type (import.source.csv)."
            )

        _logger.debug(
            "Handler %s: Retrieved source_config via backend search: %s (ID: %s, Model: %s) from recordset %s (ID: %s)",
            self._name,
            source_config.display_name,
            source_config.id,
            source_config._name,
            recordset_record.name,
            recordset_record.id,
        )

        return source_config.sudo()

    def _prepare_second_hand_product_vals(self, main_odoo_template):
        source_config = self._get_source_config()
        if not main_odoo_template.barcode:
            _logger.warning(
                "Handler %s: Cannot prepare second-hand product for template ID %s - main product has no barcode.",
                self._name,
                main_odoo_template.id,
            )
            return None

        original_barcode = main_odoo_template.barcode
        second_hand_suffix = (
            source_config.second_hand_suffix
            if source_config.second_hand_suffix
            else "_SH"
        )

        second_hand_barcode = original_barcode + second_hand_suffix
        max_barcode_length = 16
        if len(second_hand_barcode) > max_barcode_length:
            _logger.warning(
                f"Handler %s: Generated second-hand barcode '{second_hand_barcode}' exceeds {max_barcode_length} characters for main barcode '{original_barcode}' (Template ID: {main_odoo_template.id}, Source Config ID: {source_config.id}). Truncating barcode.",
                self._name,
            )
            second_hand_barcode = second_hand_barcode[:max_barcode_length]
            _logger.warning(
                f"Handler %s: Truncated second-hand barcode to: '{second_hand_barcode}'",
                self._name,
            )

        second_hand_vals = {
            "name": f"{main_odoo_template.name} ({source_config.second_hand_default_code})",
            "barcode": second_hand_barcode,
            "default_code": source_config.second_hand_default_code,
            "list_price": main_odoo_template.list_price,
            "standard_price": main_odoo_template.standard_price,
            "weight": main_odoo_template.weight,
            "sale_ok": main_odoo_template.sale_ok,
            "detailed_type": main_odoo_template.detailed_type,
            "categ_id": main_odoo_template.categ_id.id
            if main_odoo_template.categ_id
            else False,
            "description_sale": main_odoo_template.description_sale,
            "description": main_odoo_template.description,
            "image_1920": main_odoo_template.image_1920,
            "company_id": main_odoo_template.company_id.id
            if main_odoo_template.company_id
            else False,
        }

        all_tag_ids = list(main_odoo_template.product_tag_ids.ids)

        try:
            snd_hand_tag = self.env.ref(
                "canalocio_importer.product_tag_second_hand", raise_if_not_found=False
            )
            if snd_hand_tag:
                if snd_hand_tag.id not in all_tag_ids:
                    all_tag_ids.append(snd_hand_tag.id)
            else:
                _logger.warning(
                    "Handler %s: Specific 'Second-hand' tag (connector_importer_canal.product_tag_second_hand) not found. Skipping tag addition.",
                    self._name,
                )
        except Exception as e:
            _logger.error(
                "Handler %s: Error getting 'Second-hand' tag ref: %s", self._name, e
            )

        second_hand_vals["product_tag_ids"] = [Command.set(all_tag_ids)]

        return second_hand_vals

    def odoo_post_create(self, odoo_record, values, orig_values):
        """
        Called after a main product.template record is successfully created.
        Creates a corresponding second-hand product.
        """
        _logger.info(
            "Handler %s: Post-create handler for main product template ID: %s (Barcode: %s)",
            self._name,
            odoo_record.id,
            odoo_record.barcode,
        )

        second_hand_vals = self._prepare_second_hand_product_vals(odoo_record)

        if not second_hand_vals:
            _logger.info(
                "Handler %s: Skipping second-hand product creation for template ID %s (main barcode: %s) due to validation failure in _prepare_second_hand_product_vals.",
                self._name,
                odoo_record.id,
                odoo_record.barcode,
            )
            return

        existing_snd_hand_product = (
            self.env["product.template"]
            .with_context(active_test=False)
            .search(
                [
                    ("barcode", "=", second_hand_vals.get("barcode")),
                    (
                        "company_id",
                        "=",
                        odoo_record.company_id.id if odoo_record.company_id else False,
                    ),
                ],
                limit=1,
            )
        )

        if existing_snd_hand_product:
            _logger.warning(
                f"Handler %s: Second-hand product with barcode '{second_hand_vals.get('barcode')}' already exists (ID: {existing_snd_hand_product.id}, Active: {existing_snd_hand_product.active}). Skipping creation for main product ID {odoo_record.id}.",
                self._name,
            )
            return

        _logger.info(
            "Handler %s: Attempting to create second-hand product for main template ID: %s (main barcode: %s) with barcode: %s",
            self._name,
            odoo_record.id,
            odoo_record.barcode,
            second_hand_vals.get("barcode", "N/A"),
        )

        try:
            snd_hand_product = self.env["product.template"].create(second_hand_vals)

            _logger.info(
                "Handler %s: Created second-hand product template ID: %s (Barcode: %s) for main template ID: %s",
                self._name,
                snd_hand_product.id,
                snd_hand_product.barcode,
                odoo_record.id,
            )

        except Exception as e:
            _logger.error(
                f"Handler %s: Failed to create second-hand product for main template ID {odoo_record.id} "
                f"with proposed barcode {second_hand_vals.get('barcode', 'N/A')}: {e}",
                self._name,
                exc_info=True,
            )

    def odoo_post_write(self, odoo_record, values, orig_values):
        """
        Called after a main product.template record is successfully updated.
        Updates the corresponding second-hand product.
        """
        _logger.info(
            "Handler %s: Post-write handler for main product template ID: %s (Barcode: %s)",
            self._name,
            odoo_record.id,
            odoo_record.barcode,
        )

        source_config = self._get_source_config()

        if not odoo_record.barcode:
            _logger.warning(
                "Handler %s: Cannot update second-hand product for template ID %s - main product has no barcode.",
                self._name,
                odoo_record.id,
            )
            return

        original_barcode = odoo_record.barcode
        second_hand_suffix = (
            source_config.second_hand_suffix
            if source_config.second_hand_suffix
            else "_SH"
        )

        expected_second_hand_barcode = original_barcode + second_hand_suffix
        max_barcode_length = 16
        if len(expected_second_hand_barcode) > max_barcode_length:
            _logger.warning(
                f"Handler %s: Generated second-hand barcode '{expected_second_hand_barcode}' exceeds {max_barcode_length} characters for main barcode '{original_barcode}' (Template ID: {odoo_record.id}, Source Config ID: {source_config.id}). Truncating barcode for search.",
                self._name,
            )
            expected_second_hand_barcode = expected_second_hand_barcode[
                :max_barcode_length
            ]
            _logger.warning(
                f"Handler %s: Using truncated second-hand barcode for search/update: '{expected_second_hand_barcode}'",
                self._name,
            )

        existing_second_hand_product_template = (
            self.env["product.template"]
            .with_context(active_test=False)
            .search(
                [
                    ("barcode", "=", expected_second_hand_barcode),
                    (
                        "company_id",
                        "=",
                        odoo_record.company_id.id if odoo_record.company_id else False,
                    ),
                ],
                limit=1,
            )
        )

        if not existing_second_hand_product_template:
            _logger.warning(
                f"Handler %s: Could not find existing second-hand product with barcode '{expected_second_hand_barcode}' "
                f"for main product ID {odoo_record.id}. Skipping update. (Maybe it needs to be created? This can happen if the main product was created before the second-hand logic existed, or if there was a previous error.)",
                self._name,
            )
            return

        _logger.info(
            "Handler %s: Attempting to update second-hand product template ID %s (barcode: %s) for main product ID %s",
            self._name,
            existing_second_hand_product_template.id,
            expected_second_hand_barcode,
            odoo_record.id,
        )

        updated_main_vals = odoo_record.read(
            [
                "name",
                "list_price",
                "standard_price",
                "weight",
                "sale_ok",
                "detailed_type",
                "categ_id",
                "description_sale",
                "description",
                "image_1920",
                "product_tag_ids",
                "active",
                "company_id",
            ]
        )[0]

        update_vals = {
            "name": f"{updated_main_vals.get('name', '')} ({source_config.second_hand_default_code})",
            "barcode": expected_second_hand_barcode,
            "default_code": source_config.second_hand_default_code,
            "list_price": updated_main_vals.get("list_price", 0.0),
            "standard_price": updated_main_vals.get("standard_price", 0.0),
            "weight": updated_main_vals.get("weight", 0.0),
            "sale_ok": updated_main_vals.get("sale_ok", False),
            "detailed_type": updated_main_vals.get("detailed_type", "product"),
            "categ_id": updated_main_vals.get("categ_id")[0]
            if updated_main_vals.get("categ_id")
            and isinstance(updated_main_vals.get("categ_id"), (list, tuple))
            else False,
            "description_sale": updated_main_vals.get("description_sale", False),
            "description": updated_main_vals.get("description", False),
            "image_1920": updated_main_vals.get("image_1920", False),
            "active": updated_main_vals.get("active", False),
            "company_id": updated_main_vals.get("company_id")[0]
            if updated_main_vals.get("company_id")
            and isinstance(updated_main_vals.get("company_id"), (list, tuple))
            else False,
        }

        all_tag_ids = list(odoo_record.product_tag_ids.ids)

        try:
            snd_hand_tag = self.env.ref(
                "canalocio_importer.product_tag_second_hand", raise_if_not_found=False
            )
            if snd_hand_tag:
                if snd_hand_tag.id not in all_tag_ids:
                    all_tag_ids.append(snd_hand_tag.id)
            elif not snd_hand_tag:
                _logger.warning(
                    "Handler %s: Specific 'Second-hand' tag (connector_importer_canal.product_tag_second_hand) not found during update. Skipping tag addition.",
                    self._name,
                )

        except Exception as e:
            _logger.error(
                "Handler %s: Error getting 'Second-hand' tag ref during update: %s",
                self._name,
                e,
            )

        update_vals["product_tag_ids"] = [Command.set(all_tag_ids)]

        try:
            existing_second_hand_product_template.write(update_vals)

            _logger.info(
                "Handler %s: Successfully updated second-hand product template ID: %s",
                self._name,
                existing_second_hand_product_template.id,
            )

        except Exception as e:
            _logger.error(
                f"Handler %s: Failed to update second-hand product template ID {existing_second_hand_product_template.id} "
                f"(barcode: {expected_second_hand_barcode}): {e}",
                self._name,
                exc_info=True,
            )
