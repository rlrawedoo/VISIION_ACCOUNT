# -*- coding: utf-8 -*-
{
    "name": "Account extra Discounts",
    "version": "1.0.0",
    "author": "Antonio Hermosilla <ahermosilla@visiion.net>",
    "license": "AGPL-3",
    "category": 'Account',
    'website': 'www.visiion.net',
    'depends': [
        'account',
    ],
    'data': [
        #'security/security.xml',
        'security/ir.model.access.csv',
        #'data/account.tax.csv',
        'views/account_invoice_view.xml',
        #'views/account_tax_view.xml',
    ],
    'installable': True,
    'auto_install': False,
}
