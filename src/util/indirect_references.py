# -*- coding: utf-8 -*-
import collections

from .helpers import model_of_table, table_of_model
from .pg import column_exists, table_exists


class IndirectReference(collections.namedtuple("IndirectReference", "table res_model res_id res_model_id set_unknown")):
    def model_filter(self, prefix="", placeholder="%s"):
        if prefix and prefix[-1] != ".":
            prefix += "."
        if self.res_model_id:
            placeholder = "(SELECT id FROM ir_model WHERE model={})".format(placeholder)
            column = self.res_model_id
        else:
            column = self.res_model

        return '{}"{}"={}'.format(prefix, column, placeholder)


# By default, there is no `res_id`, no `res_model_id` and it is deleted when the linked model is removed
IndirectReference.__new__.__defaults__ = (None, None, False)  # https://stackoverflow.com/a/18348004


def indirect_references(cr, bound_only=False):
    IR = IndirectReference
    each = [
        IR("ir_attachment", "res_model", "res_id"),
        IR("ir_cron", "model", None, set_unknown=True),
        IR("ir_act_report_xml", "model", None, set_unknown=True),
        IR("ir_act_window", "res_model", "res_id"),
        IR("ir_act_window", "src_model", None),
        IR("ir_act_server", "wkf_model_name", None),
        IR("ir_act_server", "crud_model_name", None),
        IR("ir_act_server", "model_name", None, "model_id", set_unknown=True),
        IR("ir_act_client", "res_model", None, set_unknown=True),
        IR("ir_model", "model", None),
        IR("ir_model_fields", "model", None),
        IR("ir_model_fields", "relation", None),  # destination of a relation field
        IR("ir_model_data", "model", "res_id"),
        IR("ir_filters", "model_id", None, set_unknown=True),  # YUCK!, not an id
        IR("ir_exports", "resource", None, set_unknown=True),
        IR("ir_ui_view", "model", None, set_unknown=True),
        IR("ir_values", "model", "res_id"),
        IR("wkf_transition", "trigger_model", None),
        IR("wkf_triggers", "model", None),
        IR("ir_model_fields_anonymization", "model_name", None),
        IR("ir_model_fields_anonymization_migration_fix", "model_name", None),
        IR("base_import_import", "res_model", None),
        IR("calendar_event", "res_model", "res_id"),  # new in saas~18
        IR("documents_document", "res_model", "res_id"),
        IR("email_template", "model", None, set_unknown=True),  # stored related
        IR("mail_template", "model", None, set_unknown=True),  # model renamed in saas~6
        IR("mail_activity", "res_model", "res_id", "res_model_id"),
        IR("mail_alias", None, "alias_force_thread_id", "alias_model_id"),
        IR("mail_alias", None, "alias_parent_thread_id", "alias_parent_model_id"),
        IR("mail_followers", "res_model", "res_id"),
        IR("mail_message_subtype", "res_model", None),
        IR("mail_message", "model", "res_id"),
        IR("mail_compose_message", "model", "res_id"),
        IR("mail_wizard_invite", "res_model", "res_id"),
        IR("mail_mail_statistics", "model", "res_id"),
        IR("mailing_trace", "model", "res_id"),
        IR("mail_mass_mailing", "mailing_model", None, "mailing_model_id", set_unknown=True),
        IR("mailing_mailing", None, None, "mailing_model_id", set_unknown=True),
        IR("project_project", "alias_model", None, set_unknown=True),
        IR("rating_rating", "res_model", "res_id", "res_model_id"),
        IR("rating_rating", "parent_res_model", "parent_res_id", "parent_res_model_id"),
        IR("timer_timer", "res_model", "res_id"),
    ]

    for ir in each:
        if bound_only and not ir.res_id:
            continue
        if ir.res_id and not column_exists(cr, ir.table, ir.res_id):
            continue

        # some `res_model/res_model_id` combination may change between
        # versions (i.e. rating_rating.res_model_id was added in saas~15).
        # we need to verify existance of columns before using them.
        if ir.res_model and not column_exists(cr, ir.table, ir.res_model):
            ir = ir._replace(res_model=None)
        if ir.res_model_id and not column_exists(cr, ir.table, ir.res_model_id):
            ir = ir._replace(res_model_id=None)
        if not ir.res_model and not ir.res_model_id:
            continue

        yield ir


def generate_indirect_reference_cleaning_queries(cr, ir):
    """Generator that yield queries to clean an `IndirectReference`"""

    if ir.res_model:
        query = """
            SELECT {ir.res_model}
              FROM {ir.table}
             WHERE {ir.res_model} IS NOT NULL
          GROUP BY {ir.res_model}
        """
    else:
        query = """
            SELECT m.model
              FROM {ir.table} t
              JOIN ir_model m ON m.id = t.{ir.res_model_id}
          GROUP BY m.model
        """
    cr.execute(query.format(ir=ir))
    for (model,) in cr.fetchall():
        res_table = table_of_model(cr, model)
        if table_exists(cr, res_table):
            cond = "NOT EXISTS (SELECT 1 FROM {res_table} r WHERE r.id = t.{ir.res_id})".format(**locals())
        else:
            cond = "true"

        model_filter = ir.model_filter()
        yield cr.mogrify(
            "DELETE FROM {ir.table} t WHERE {model_filter} AND {cond}".format(**locals()), [model]
        ).decode()


def res_model_res_id(cr, filtered=True):
    for ir in indirect_references(cr):
        if ir.res_model:
            yield model_of_table(cr, ir.table), ir.res_model, ir.res_id
