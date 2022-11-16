# -*- encoding: utf-8 -*-

from odoo import fields, models, api, exceptions, _


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    allow_unbalanced_moves = fields.Boolean(
        string=_('Allow Unbalanced Moves'),
    )



class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.multi
    def assert_balanced(self):
        if self.journal_id.allow_unbalanced_moves:
            return True
        return super(AccountMove,self).assert_balanced()
