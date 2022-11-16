# -*- encoding: utf-8 -*-

from odoo import fields, models, api, exceptions, _
from odoo.addons import decimal_precision as dp
from odoo.addons.account.models.account_invoice import AccountInvoice


class AccountInvoiceLineDiscounts(models.Model):
    _name = 'account.invoice.line.discounts'

    @api.one
    @api.depends('price_unit', 'discount', 'invoice_line_tax_ids', 'quantity',
        'product_id', 'invoice_id.partner_id', 'invoice_id.currency_id', 'invoice_id.company_id',
        'invoice_id.date_invoice', 'invoice_id.date')
    def _compute_price(self):
        currency = self.invoice_id and self.invoice_id.currency_id or None
        price = self.price_unit #* (1 - (self.discount or 0.0) / 100.0)
        taxes = False
        if self.invoice_line_tax_ids:
            taxes = self.invoice_line_tax_ids.compute_all(price, currency, self.quantity, product=self.product_id, partner=self.invoice_id.partner_id)
        self.price_subtotal = price_subtotal_signed = taxes['total_excluded'] if taxes else self.quantity * price
        self.price_total = taxes['total_included'] if taxes else self.price_subtotal
        if self.invoice_id.currency_id and self.invoice_id.currency_id != self.invoice_id.company_id.currency_id:
            currency = self.invoice_id.currency_id
            date = self.invoice_id._get_currency_rate_date()
            price_subtotal_signed = currency._convert(price_subtotal_signed, self.invoice_id.company_id.currency_id, self.company_id or self.env.user.company_id, date or fields.Date.today())
        sign = self.invoice_id.type in ['in_refund', 'out_refund'] and -1 or 1
        self.price_subtotal_signed = price_subtotal_signed * sign

    @api.model
    def _default_account(self):
        if self._context.get('journal_id'):
            journal = self.env['account.journal'].browse(self._context.get('journal_id'))
            if self._context.get('type') in ('out_invoice', 'in_refund'):
                return journal.default_credit_account_id.id
            return journal.default_debit_account_id.id
    
    sequence = fields.Integer(default=10,
        help="Gives the sequence of this line when displaying the invoice.")

    invoice_id = fields.Many2one(
        comodel_name='account.invoice',
        string="Factura"
    )

    compute_type = fields.Selection(
        selection=[
            ('discount','Descuento'),
            ('charge','Cargo'),
        ],
        string="Tipo",
        default='discount',
    )

    compute_mode = fields.Selection(
        selection=[
            ('percent','Porcentaje'),
            ('amount','Importe'),
        ],
        string="Modo de calculo",
        default='percent',
    )

    name = fields.Text(string='Descripción', required=True)

    invoice_type = fields.Selection(related='invoice_id.type', readonly=True)
    
    product_id = fields.Many2one('product.product', string='Producto',
        ondelete='restrict', index=True)

    account_id = fields.Many2one('account.account', string='Cuenta', domain=[('deprecated', '=', False)],
        default=_default_account,
        help="The income or expense account related to the selected product.")

    price_unit = fields.Float(
        string='Precio', 
        required=True, 
        digits=dp.get_precision('Product Price'),
        default=0.0
    )
    price_subtotal = fields.Monetary(string='Amount (without Taxes)',
        store=True, readonly=True, compute='_compute_price', help="Total amount without taxes")
    price_total = fields.Monetary(string='Amount (with Taxes)',
        store=True, readonly=True, compute='_compute_price', help="Total amount with taxes")
    price_subtotal_signed = fields.Monetary(string='Amount Signed', currency_field='company_currency_id',
        store=True, readonly=True, compute='_compute_price',
        help="Total amount in the currency of the company, negative for credit note.")
    price_tax = fields.Monetary(string='Tax Amount', compute='_get_price_tax', store=False)
    quantity = fields.Float(string='Quantity', digits=dp.get_precision('Product Unit of Measure'),
        required=True, default=1)
    discount = fields.Float(string='Desc (%)', digits=dp.get_precision('Discount'),
        default=0.0)
    invoice_line_tax_ids = fields.Many2many('account.tax',
        'account_invoice_line_discount_tax', 'invoice_line_discount_id', 'tax_id',
        string='Taxes', domain=[('type_tax_use','!=','none'), '|', ('active', '=', False), ('active', '=', True)], oldname='invoice_line_tax_id')
    account_analytic_id = fields.Many2one('account.analytic.account',
        string='Analytic Account')
    analytic_tag_ids = fields.Many2many('account.analytic.tag', string='Analytic Tags')
    company_id = fields.Many2one('res.company', string='Company',
        related='invoice_id.company_id', store=True, readonly=True, related_sudo=False)
    partner_id = fields.Many2one('res.partner', string='Partner',
        related='invoice_id.partner_id', store=True, readonly=True, related_sudo=False)
    currency_id = fields.Many2one('res.currency', related='invoice_id.currency_id', store=True, related_sudo=False, readonly=False)
    company_currency_id = fields.Many2one('res.currency', related='invoice_id.company_currency_id', readonly=True, related_sudo=False)
    is_rounding_line = fields.Boolean(string='Rounding Line', help='Is a rounding line in case of cash rounding.')

    uom_id = fields.Many2one('uom.uom', string='Unit of Measure',
        ondelete='set null', index=True, oldname='uos_id')

    def _get_price_tax(self):
        for l in self:
            l.price_tax = l.price_total - l.price_subtotal

    @api.v8
    def get_invoice_line_account(self, type, product, fpos, company):
        accounts = product.product_tmpl_id.get_product_accounts(fpos)
        if type in ('out_invoice', 'out_refund'):
            return accounts['income']
        return accounts['expense']

    def _set_currency(self):
        company = self.invoice_id.company_id
        currency = self.invoice_id.currency_id
        if company and currency:
            if company.currency_id != currency:
                self.price_unit = self.price_unit * currency.with_context(dict(self._context or {}, date=self.invoice_id.date_invoice)).rate

    def _set_taxes(self):
        """ Used in on_change to set taxes and price"""
        self.ensure_one()

        # Keep only taxes of the company
        company_id = self.company_id or self.env.user.company_id

        if self.invoice_id.type in ('out_invoice', 'out_refund'):
            taxes = self.product_id.taxes_id.filtered(lambda r: r.company_id == company_id) or self.account_id.tax_ids or self.invoice_id.company_id.account_sale_tax_id
        else:
            taxes = self.product_id.supplier_taxes_id.filtered(lambda r: r.company_id == company_id) or self.account_id.tax_ids or self.invoice_id.company_id.account_purchase_tax_id

        self.invoice_line_tax_ids = fp_taxes = self.invoice_id.fiscal_position_id.map_tax(taxes, self.product_id, self.invoice_id.partner_id)

        fix_price = self.env['account.tax']._fix_tax_included_price
        if self.invoice_id.type in ('in_invoice', 'in_refund'):
            prec = self.env['decimal.precision'].precision_get('Product Price')
            if not self.price_unit or float_compare(self.price_unit, self.product_id.standard_price, precision_digits=prec) == 0:
                self.price_unit = fix_price(self.product_id.standard_price, taxes, fp_taxes)
                self._set_currency()
        else:
            self.price_unit = fix_price(self.product_id.lst_price, taxes, fp_taxes)
            self._set_currency()

    @api.onchange('product_id')
    def _onchange_product_id(self):
        domain = {}
        if not self.invoice_id:
            return

        part = self.invoice_id.partner_id
        fpos = self.invoice_id.fiscal_position_id
        company = self.invoice_id.company_id
        currency = self.invoice_id.currency_id
        type = self.invoice_id.type

        if not part:
            warning = {
                    'title': _('Warning!'),
                    'message': _('You must first select a partner.'),
                }
            return {'warning': warning}

        if not self.product_id:
            if type not in ('in_invoice', 'in_refund'):
                self.price_unit = 0.0
            domain['uom_id'] = []
        else:
            self_lang = self
            if part.lang:
                self_lang = self.with_context(lang=part.lang)

            product = self_lang.product_id
            account = self.get_invoice_line_account(type, product, fpos, company)
            if account:
                self.account_id = account.id
            self._set_taxes()

            product_name = self_lang._get_invoice_line_name_from_product()
            if product_name != None:
                self.name = product_name

            if not self.uom_id or product.uom_id.category_id.id != self.uom_id.category_id.id:
                self.uom_id = product.uom_id.id
            domain['uom_id'] = [('category_id', '=', product.uom_id.category_id.id)]

            if company and currency:

                if self.uom_id and self.uom_id.id != product.uom_id.id:
                    self.price_unit = product.uom_id._compute_price(self.price_unit, self.uom_id)
        return {'domain': domain}

    def _get_invoice_line_name_from_product(self):
        """ Returns the automatic name to give to the invoice line depending on
        the product it is linked to.
        """
        self.ensure_one()
        if not self.product_id:
            return ''
        invoice_type = self.invoice_id.type
        rslt = self.product_id.partner_ref
        if invoice_type in ('in_invoice', 'in_refund'):
            if self.product_id.description_purchase:
                rslt += '\n' + self.product_id.description_purchase
        else:
            if self.product_id.description_sale:
                rslt += '\n' + self.product_id.description_sale

        return rslt

    @api.onchange('discount','price_unit')
    def onchange_discount(self):
        # Subtotal de lineas
        amount_untaxed_lines = sum(line.price_subtotal for line in self.invoice_id.invoice_line_ids)
        account_invoice_line_discount_ids = self.invoice_id.account_invoice_line_discount_ids
        print(account_invoice_line_discount_ids)
        for line_dis in account_invoice_line_discount_ids.sorted(key =lambda x:x.sequence):
            if line_dis.compute_type == 'charge':
                round_curr = line_dis.currency_id.round
                if line_dis.compute_mode == 'percent':
                    amount_discount = amount_untaxed_lines * (line_dis.discount/100.0)
                    line_dis.price_unit = amount_discount
                    line_dis.update({
                        'price_unit':amount_discount
                    })
                else:
                    amount_discount = line_dis.price_unit
                    line_dis.price_unit = amount_discount
                    line_dis.update({
                        'price_unit':amount_discount
                    })
                amount_untaxed_lines +=line_dis.price_subtotal
                continue
            elif line_dis.compute_type == 'discount':
                round_curr = line_dis.currency_id.round
                if line_dis.compute_mode == 'percent':
                    amount_discount = amount_untaxed_lines * (line_dis.discount/100.0)
                    line_dis.price_unit = amount_discount
                    line_dis.update({
                        'price_unit':amount_discount
                    })
                else:
                    amount_discount = line_dis.price_unit
                    line_dis.price_unit = amount_discount
                    line_dis.update({
                        'price_unit':amount_discount
                    })
                amount_untaxed_lines -=line_dis.price_subtotal
                continue




        # account_invoice_line_discount_ids = self.invoice_id.account_invoice_line_discount_ids.filtered(
        #     lambda x: x.compute_type == 'charge'
        # )
        # for line_dis in account_invoice_line_discount_ids.sorted(key =lambda x:x.sequence):
        #     print(line_dis)
        #     round_curr = line_dis.currency_id.round
        #     if line_dis.compute_mode == 'percent':
        #         amount_discount = amount_untaxed_lines * (line_dis.discount/100.0)
        #     else:
        #         amount_discount = line_dis.price_unit
        #     line_dis.price_unit = amount_discount
        #     line_dis.update({
        #         'price_unit':amount_discount
        #     })
        #     amount_untaxed_lines +=amount_discount
        



        # # print(amount_untaxed_lines)
        # # Añadir los cargos extras.
        # # amount_untaxed_lines += sum(line.price_subtotal if line.compute_type == 'charge' else 0.0 for line in self.invoice_id.account_invoice_line_discount_ids )
        # # print(amount_untaxed_lines)
        # account_invoice_line_discount_ids = self.invoice_id.account_invoice_line_discount_ids.filtered(
        #     lambda x: x.compute_type == 'discount'
        # ) #x.sequence < self.sequence and
        # print(account_invoice_line_discount_ids)

        # for line_dis in account_invoice_line_discount_ids.sorted(key =lambda x:x.sequence):
        #     print(line_dis)
        #     round_curr = line_dis.currency_id.round
        #     if line_dis.compute_mode == 'percent':
        #         amount_discount = amount_untaxed_lines * (line_dis.discount/100.0)
        #     else:
        #         amount_discount = line_dis.price_unit
        #     line_dis.price_unit = amount_discount
        #     line_dis.update({
        #         'price_unit':amount_discount
        #     })
        #     amount_untaxed_lines -=amount_discount



        # if account_invoice_line_discount_ids:
        #     amount_untaxed_lines -= sum(line.price_subtotal for line in account_invoice_line_discount_ids )
        # #print(amount_untaxed_lines)
        # #amount_untaxed_lines = self.invoice_id.amount_untaxed
        # print(self)
        # for inv_line in self:
        #     if inv_line.compute_type == 'discount':
        #         #amount_untaxed_lines += inv_line.price_subtotal
        #         #print(amount_untaxed_lines)
        #         round_curr = inv_line.currency_id.round
        #         amount_discount = amount_untaxed_lines * (inv_line.discount/100.0)
        #         inv_line.price_unit = amount_discount
        #         inv_line.update({
        #             'price_unit':amount_discount
        #         })
                #amount_untaxed_lines -= amount_discount
        #print("End")

def _execute_onchanges_discounts(records, field_name):
    """Helper methods that executes all onchanges associated to a field."""
    for onchange in records._onchange_methods.get(field_name, []):
        for record in records:
            record._origin = record.env['account.invoice.line.discounts']
            onchange(record)

class AccountInvoiceInherit(models.Model):
    _inherit = 'account.invoice'

    account_invoice_line_discount_ids = fields.One2many(
        comodel_name='account.invoice.line.discounts',
        inverse_name='invoice_id',
    )



    # @api.onchange('account_invoice_line_discount_ids')
    # def onchange_discount(self):
        
    #     amount_untaxed_lines = sum(line.price_subtotal for line in self.invoice_line_ids)
    #     #Añadir los cargos extras.
    #     amount_untaxed_lines += sum(line.price_subtotal if line.compute_type == 'charge' else 0.0 for line in self.account_invoice_line_discount_ids )
    #     #amount_untaxed_lines -= sum(line.price_subtotal if line.compute_type == 'discount' else 0.0 for line in self.account_invoice_line_discount_ids )

    #     for inv_line in self.account_invoice_line_discount_ids:
    #         print(inv_line)
    #         if inv_line.compute_type == 'discount':
    #             round_curr = inv_line.currency_id.round
    #             amount_discount = amount_untaxed_lines * (inv_line.discount/100.0)
    #             inv_line.price_unit = amount_discount
    #             inv_line.update({
    #                 'price_unit':amount_discount
    #             })
    #             amount_untaxed_lines -= amount_discount
    @api.onchange('invoice_line_ids','account_invoice_line_discount_ids')
    def _onchange_invoice_discounts_line_ids(self):
        DiscLines = self.env['account.invoice.line.discounts']
        for line in self.account_invoice_line_discount_ids:
            if line.compute_type == 'discount':
                _execute_onchanges_discounts(line, 'discount')
            else:
                _execute_onchanges_discounts(line, 'price_unit')

    @api.onchange('invoice_line_ids','account_invoice_line_discount_ids')
    def _onchange_invoice_line_ids(self):
        taxes_grouped = self.get_taxes_values()
        tax_lines = self.tax_line_ids.filtered('manual')
        for tax in taxes_grouped.values():
            tax_lines += tax_lines.new(tax)
        self.tax_line_ids = tax_lines
        return

    #'account_invoice_line_discount_ids.price_subtotal',
    @api.one
    @api.depends('invoice_line_ids.price_subtotal', 'tax_line_ids.amount', 'tax_line_ids.amount_rounding',
                 'currency_id', 'company_id', 'date_invoice', 'type')
    def _compute_amount_new(self):
        round_curr = self.currency_id.round
        amount_untaxed = sum(line.price_subtotal for line in self.invoice_line_ids)
        for lin_dis in self.account_invoice_line_discount_ids:
            if lin_dis.compute_type == 'discount':
                amount_untaxed -= lin_dis.price_subtotal
            elif lin_dis.compute_type == 'charge':
                amount_untaxed += lin_dis.price_subtotal


        self.amount_untaxed = amount_untaxed
        self.amount_tax = sum(round_curr(line.amount_total) for line in self.tax_line_ids)
        self.amount_total = self.amount_untaxed + self.amount_tax
        amount_total_company_signed = self.amount_total
        amount_untaxed_signed = self.amount_untaxed
        if self.currency_id and self.company_id and self.currency_id != self.company_id.currency_id:
            currency_id = self.currency_id
            amount_total_company_signed = currency_id._convert(self.amount_total, self.company_id.currency_id, self.company_id, self.date_invoice or fields.Date.today())
            amount_untaxed_signed = currency_id._convert(self.amount_untaxed, self.company_id.currency_id, self.company_id, self.date_invoice or fields.Date.today())
        sign = self.type in ['in_refund', 'out_refund'] and -1 or 1
        self.amount_total_company_signed = amount_total_company_signed * sign
        self.amount_total_signed = self.amount_total * sign
        self.amount_untaxed_signed = amount_untaxed_signed * sign

    # def _compute_sign_taxes_new(self):
    #     for invoice in self:
    #         sign = invoice.type in ['in_refund', 'out_refund'] and -1 or 1
    #         invoice.amount_untaxed_invoice_signed = invoice.amount_untaxed * sign
    #         invoice.amount_tax_signed = invoice.amount_tax * sign

    AccountInvoice._compute_amount_old = AccountInvoice._compute_amount
    AccountInvoice._compute_amount = _compute_amount_new

    @api.multi
    def get_taxes_values_new(self):
        tax_grouped = {}
        round_curr = self.currency_id.round
        for line in self.invoice_line_ids:
            if not line.account_id:
                continue
            price_unit = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            taxes = line.invoice_line_tax_ids.compute_all(price_unit, self.currency_id, line.quantity, line.product_id, self.partner_id)['taxes']
            for tax in taxes:
                val = self._prepare_tax_line_vals(line, tax)
                key = self.env['account.tax'].browse(tax['id']).get_grouping_key(val)

                if key not in tax_grouped:
                    tax_grouped[key] = val
                    tax_grouped[key]['base'] = round_curr(val['base'])
                else:
                    tax_grouped[key]['amount'] += val['amount']
                    tax_grouped[key]['base'] += round_curr(val['base'])

        for line_dic in self.account_invoice_line_discount_ids:
            if not line_dic.account_id:
                continue
            price_unit = line_dic.price_unit
            if line_dic.compute_type == 'discount':
                price_unit = -price_unit
            taxes = line_dic.invoice_line_tax_ids.compute_all(price_unit, self.currency_id, line_dic.quantity, line_dic.product_id, self.partner_id)['taxes']
            for tax in taxes:
                val = self._prepare_tax_line_vals(line_dic, tax)
                key = self.env['account.tax'].browse(tax['id']).get_grouping_key(val)
                #print(val)
                #input("lo de los ivas")
                if key not in tax_grouped:
                    tax_grouped[key] = val
                    tax_grouped[key]['base'] = round_curr(val['base'])
                else:
                    tax_grouped[key]['amount'] += val['amount']
                    tax_grouped[key]['base'] += round_curr(val['base'])
        #print(tax_grouped)
        #input("osnddvos")
        return tax_grouped

    AccountInvoice.get_taxes_values_old = AccountInvoice.get_taxes_values
    AccountInvoice.get_taxes_values = get_taxes_values_new


    @api.model
    def invoice_line_discounts_move_line_get(self):
        res = []
        for line in self.account_invoice_line_discount_ids:
            if not line.account_id:
                continue
            if line.quantity==0:
                continue
            tax_ids = []
            for tax in line.invoice_line_tax_ids:
                tax_ids.append((4, tax.id, None))
                for child in tax.children_tax_ids:
                    if child.type_tax_use != 'none':
                        tax_ids.append((4, child.id, None))
            analytic_tag_ids = [(4, analytic_tag.id, None) for analytic_tag in line.analytic_tag_ids]
            price_unit = price_subtotal = 0.0
            if line.compute_type =='discount':
                price_unit = -line.price_unit
                price_subtotal = -line.price_subtotal
            else:
                price_unit = line.price_unit
                price_subtotal = line.price_subtotal
            move_line_dict = {
                #'invl_id': line.id,
                'type': 'src',
                'name': line.name,
                'price_unit': price_unit,
                'quantity': line.quantity,
                'price': price_subtotal,
                'account_id': line.account_id.id,
                'product_id': line.product_id.id,
                'uom_id': line.uom_id.id,
                'account_analytic_id': line.account_analytic_id.id,
                'analytic_tag_ids': analytic_tag_ids,
                'tax_ids': tax_ids,
                'invoice_id': self.id,
            }
            res.append(move_line_dict)
        return res


    @api.multi
    def action_move_create_new(self):
        """ Creates invoice related analytics and financial move lines """
        account_move = self.env['account.move']

        for inv in self:
            if not inv.journal_id.sequence_id:
                raise UserError(_('Please define sequence on the journal related to this invoice.'))
            if not inv.invoice_line_ids.filtered(lambda line: line.account_id):
                raise UserError(_('Please add at least one invoice line.'))
            if inv.move_id:
                continue


            if not inv.date_invoice:
                inv.write({'date_invoice': fields.Date.context_today(self)})
            if not inv.date_due:
                inv.write({'date_due': inv.date_invoice})
            company_currency = inv.company_id.currency_id

            # create move lines (one per invoice line + eventual taxes and analytic lines)
            iml = inv.invoice_line_move_line_get()
            #print(iml)
            iml += inv.tax_line_move_line_get()
            iml += inv.invoice_line_discounts_move_line_get()
            #print(iml)
            #input("ojnsonosnfsnvvsov")

            diff_currency = inv.currency_id != company_currency
            # create one move line for the total and possibly adjust the other lines amount
            total, total_currency, iml = inv.compute_invoice_totals(company_currency, iml)

            name = inv.name or ''
            if inv.payment_term_id:
                totlines = inv.payment_term_id.with_context(currency_id=company_currency.id).compute(total, inv.date_invoice)[0]
                res_amount_currency = total_currency
                for i, t in enumerate(totlines):
                    if inv.currency_id != company_currency:
                        amount_currency = company_currency._convert(t[1], inv.currency_id, inv.company_id, inv._get_currency_rate_date() or fields.Date.today())
                    else:
                        amount_currency = False

                    # last line: add the diff
                    res_amount_currency -= amount_currency or 0
                    if i + 1 == len(totlines):
                        amount_currency += res_amount_currency

                    iml.append({
                        'type': 'dest',
                        'name': name,
                        'price': t[1],
                        'account_id': inv.account_id.id,
                        'date_maturity': t[0],
                        'amount_currency': diff_currency and amount_currency,
                        'currency_id': diff_currency and inv.currency_id.id,
                        'invoice_id': inv.id
                    })
            else:
                iml.append({
                    'type': 'dest',
                    'name': name,
                    'price': total,
                    'account_id': inv.account_id.id,
                    'date_maturity': inv.date_due,
                    'amount_currency': diff_currency and total_currency,
                    'currency_id': diff_currency and inv.currency_id.id,
                    'invoice_id': inv.id
                })
            part = self.env['res.partner']._find_accounting_partner(inv.partner_id)
            line = [(0, 0, self.line_get_convert(l, part.id)) for l in iml]
            line = inv.group_lines(iml, line)

            line = inv.finalize_invoice_move_lines(line)

            date = inv.date or inv.date_invoice
            move_vals = {
                'ref': inv.reference,
                'line_ids': line,
                'journal_id': inv.journal_id.id,
                'date': date,
                'narration': inv.comment,
            }
            move = account_move.create(move_vals)
            # Pass invoice in method post: used if you want to get the same
            # account move reference when creating the same invoice after a cancelled one:
            move.post(invoice = inv)
            # make the invoice point to that move
            vals = {
                'move_id': move.id,
                'date': date,
                'move_name': move.name,
            }
            inv.write(vals)
        return True



    AccountInvoice.action_move_create_old = AccountInvoice.action_move_create
    AccountInvoice.action_move_create = action_move_create_new


    
