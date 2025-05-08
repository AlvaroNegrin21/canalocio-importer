import logging

from odoo.addons.component.core import Component

try:
    from odoo.addons.connector_importer.log import logger
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("Could not import original logger. Using standard __name__ logger.")


class CanalocioRecordImporterOverride(Component):
    _inherit = "importer.record"

    def run(self, record, is_last_importer=True, **kw):
        """
        Override run method from 'importer.record' to fix the
        .values(**options) bug, handle mapper returning None,
        and prevent 'override_existing' from being passed to ORM.
        """

        self.record = record
        if not self.record:
            msg = "NO RECORD FOUND, maybe deleted? Check your jobs!"
            logger.error(msg)
            return

        self._init_importer(self.record.recordset_id)

        for line in self._record_lines():
            line = self.prepare_line(line)
            options = self._load_mapper_options()

            odoo_record = None
            values = {}

            try:
                with self.env.cr.savepoint():
                    mapped_values = self.mapper.map_record(line)

                    values = mapped_values

                    if isinstance(values, dict):
                        orm_values_update = {
                            k: v for k, v in options.items() if k != "override_existing"
                        }
                        if orm_values_update:
                            values.update(orm_values_update)

                logger.debug(
                    "Mapped and prepared values for record %s (%s): %s",
                    line.get("_line_nr", "N/A"),
                    line.get(self.unique_key, "N/A"),
                    values,
                )

            except Exception as err:
                values = {}
                self.tracker.log_error({}, line, odoo_record, message=err)
                if self.must_break_on_error:
                    logger.error(
                        "Import failed during mapping/savepoint for record "
                        "%s (%s): %s",
                        line.get("_line_nr", "N/A"),
                        line.get(self.unique_key, "N/A"),
                        err,
                        exc_info=True,
                    )
                    raise
                logger.warning(
                    "Import skipped during mapping/savepoint for record "
                    "%s (%s) due to error: %s",
                    line.get("_line_nr", "N/A"),
                    line.get(self.unique_key, "N/A"),
                    err,
                )
                continue

            if values is None:
                logger.debug(
                    "Mapper returned None for line %s (%s). "
                    "Skipping record processing.",
                    line.get("_line_nr", "N/A"),
                    line.get(self.unique_key, "N/A"),
                )
                continue

            skip_info = self.skip_it(values, line)
            if skip_info:
                self.tracker.log_skipped(values, line, skip_info)
                continue

            try:
                with self.env.cr.savepoint():
                    logger.debug(
                        "Attempting ORM operation for record %s (%s) with "
                        "values: %s",
                        line.get("_line_nr", "N/A"),
                        line.get(self.unique_key, "N/A"),
                        values,
                    )

                    if self.record_handler.odoo_exists(values, line):
                        odoo_record = self.record_handler.odoo_write(values, line)
                        self.tracker.log_updated(values, line, odoo_record)
                    else:
                        if self.work.options.importer.write_only:
                            self.tracker.log_skipped(
                                values,
                                line,
                                {
                                    "message": "Write-only importer, "
                                    "record not found."
                                },
                            )
                            continue

                        odoo_record = self.record_handler.odoo_create(values, line)
                        self.tracker.log_created(values, line, odoo_record)

            except Exception as err:
                self.tracker.log_error(values, line, odoo_record, message=err)
                if self.must_break_on_error:
                    logger.error(
                        "Import failed during ORM operation for record " "%s (%s): %s",
                        line.get("_line_nr", "N/A"),
                        line.get(self.unique_key, "N/A"),
                        err,
                        exc_info=True,
                    )
                    if odoo_record and odoo_record.exists():
                        logger.error("Related Odoo record ID: %s", odoo_record.id)
                    raise

                logger.warning(
                    "Import skipped during ORM operation for record "
                    "%s (%s) due to error: %s",
                    line.get("_line_nr", "N/A"),
                    line.get(self.unique_key, "N/A"),
                    err,
                )
                continue

        self._do_report()
        counters = self.tracker.get_counters()
        msg = " ".join(
            [
                "CHUNK FINISHED",
                "[created: {created}]",
                "[updated: {updated}]",
                "[skipped: {skipped}]",
                "[errored: {errored}]",
            ]
        ).format(**counters)
        self.tracker._log(msg)

        self.finalize_session(record, is_last_importer=is_last_importer)

        return counters

    def required_keys(self, create=False):
        """
        Override required_keys to return only the source keys needed by the mapper.
        This prevents the base importer from incorrectly requiring
        'barcode' as a source key when 'ean13' is the actual source column.
        """
        mapper_required = self.mapper.required_keys()

        return mapper_required
