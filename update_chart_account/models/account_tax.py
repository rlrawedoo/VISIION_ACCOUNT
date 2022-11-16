# -*- encoding: utf-8 -*-

from odoo import fields, models, api, exceptions, _


class AccountDigitsUpdateWizard(models.TransientModel):
    _name = 'account.digits.update.wizard'

    number_of_digits= fields.Integer(
        string=_('Number of digits')
    )

    company_id = fields.Many2one(
        comodel_name='res.company',
        string=_('Company'),
    )


    @api.multi
    def action_update_digits(self):
        if self.number_of_digits <=6:
            return
        AccountObj = self.env['account.account']

        account_ids = AccountObj.search([
            ('company_id','=',self.company_id.id)
        ])

        for account in account_ids:
            
            if len(account.code) == self.number_of_digits:
                continue

            else:
                c_ini = account.code[0:4]
                c_fin = account.code[4:]
                c_add = '0'*(self.number_of_digits-len(account.code))
                # print(account.code[0:4])
                # print(account.code[4:])
                # print('0'*(self.number_of_digits-len(account.code)))

                account.code = c_ini + c_add + c_fin






    
