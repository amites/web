'''
    Copyright (C) 2017 Gitcoin Core

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published
    by the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with this program. If not, see <http://www.gnu.org/licenses/>.

'''

import argparse
import csv
import datetime
import os
import re
import StringIO
from itertools import imap

from django.conf import settings
from django.core.management.base import BaseCommand

import boto
from app.utils import itermerge
from boto.s3.key import Key
from dashboard.models import Bounty, Tip
from marketing.mails import send_mail

DATE_FORMAT = '%Y/%m/%d'
DATE_FORMAT_HYPHENATED = '%Y-%m-%d'
REPORT_URL_EXPIRATION_TIME = 60 * 60 * 24 * 30 # seconds

GITHUB_REPO_PATTERN = re.compile('github.com/[\w-]+/([\w-]+)')

def valid_date(v):
    try:
        return datetime.datetime.strptime(v, DATE_FORMAT)
    except ValueError:
        raise argparse.ArgumentTypeError('%s is not a date in YYYY/MM/DD format' % v)


class Command(BaseCommand):

    help = 'emails activity report of tips and bounties to settings.CONTACT_EMAIL'

    def add_arguments(self, parser):
        parser.add_argument('start_date', type=valid_date, help='Start of date range (inclusive) in YYYY/MM/DD format for activities to be collected')
        parser.add_argument('end_date', type=valid_date, help='End of date range (inclusive) in YYYY/MM/DD format for activities to be collected')

    def extract_github_repo(self, url):
        match = GITHUB_REPO_PATTERN.search(url)
        if not match:
            self.stdout.write(self.style.WARNING('WARNING: malformed github url: %s, using value as is' % url))
            return url

        return match.groups()[0]

    def format_bounty(self, bounty):
        return {
            'type': 'bounty',
            'created_on': bounty.web3_created,
            'last_activity': bounty.modified_on,
            'amount': bounty.get_natural_value(),
            'denomination': bounty.token_name,
            'amount_eth': bounty.value_in_eth,
            'amount_usdt': bounty.value_in_usdt,
            'from_address': bounty.bounty_owner_address,
            'claimee_address': bounty.claimeee_address,
            'repo': self.extract_github_repo(bounty.github_url),
            'from_username': bounty.bounty_owner_github_username or '',
            'claimee_github_username': bounty.claimee_github_username or '',
            'status': bounty.status,
            'comments': ''
        }

    def format_tip(self, tip):
        return {
            'type': 'tip',
            'created_on': tip.created_on,
            'last_activity': tip.modified_on,
            'amount': tip.get_natural_value(),
            'denomination': tip.tokenName,
            'amount_eth': tip.value_in_eth,
            'amount_usdt': tip.value_in_usdt,
            'from_address': '',
            'claimee_address': '',
            'repo': self.extract_github_repo(tip.github_url) if tip.github_url else '',
            'from_username': tip.from_email, # user tipper's email for now so tips are somewhat identifiable
            'claimee_github_username': '', # don't know who recieves this tip at the moment
            'status': tip.status,
            'comments': ''
        }

    def upload_to_s3(self, filename, contents):
        s3 = boto.connect_s3(settings.AWS_ACCESS_KEY_ID, settings.AWS_SECRET_ACCESS_KEY)
        bucket = s3.get_bucket(settings.S3_REPORT_BUCKET)

        key = Key(bucket)
        key.key = os.path.join(settings.S3_REPORT_PREFIX, filename)
        key.set_contents_from_string(contents)

        return key.generate_url(expires_in=REPORT_URL_EXPIRATION_TIME)


    def handle(self, *args, **options):
        bounties = Bounty.objects.filter(
            network='mainnet',
            current_bounty=True,
            web3_created__gte=options['start_date'],
            web3_created__lte=options['end_date']
        ).order_by('web3_created', 'id')

        tips = Tip.objects.filter(
            network='mainnet',
            created_on__gte=options['start_date'],
            created_on__lte=options['end_date']
        ).order_by('created_on', 'id')

        formatted_bounties = imap(self.format_bounty, bounties)
        formatted_tips = imap(self.format_tip, tips)

        csvfile = StringIO.StringIO()
        csvwriter = csv.DictWriter(csvfile, fieldnames=[
            'type', 'created_on', 'last_activity', 'amount', 'denomination', 'amount_eth',
            'amount_usdt', 'from_address', 'claimee_address', 'repo', 'from_username',
            'claimee_github_username', 'status', 'comments'])
        csvwriter.writeheader()

        has_rows = False
        for item in itermerge(formatted_bounties, formatted_tips, lambda x: x['created_on']):
            has_rows = True
            csvwriter.writerow(item)

        start = options['start_date'].strftime(DATE_FORMAT_HYPHENATED)
        end = options['end_date'].strftime(DATE_FORMAT_HYPHENATED)
        now = str(datetime.datetime.now())
        if has_rows:
            subject = 'Gitcoin Activity report from %s to %s' % (start, end)

            url = self.upload_to_s3('activity_report_%s_%s_generated_on_%s.csv' % (start, end, now), csvfile.getvalue())
            body = '<a href="%s">%s</a>' % (url, url)

            send_mail(settings.CONTACT_EMAIL, settings.CONTACT_EMAIL, subject, body='', html=body, add_bcc=False)

            self.stdout.write(self.style.SUCCESS('Sent activity report from %s to %s to %s' % (start, end, settings.CONTACT_EMAIL)))
        else:
            self.stdout.write(self.style.WARNING('No activity from %s to %s to report' % (start, end)))
