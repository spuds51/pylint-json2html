#!/usr/bin/env python3
"""Pylint JSON's report to HTML"""
import argparse
import collections
import json
import sys

from jinja2 import Environment, PackageLoader, select_autoescape
from pylint.interfaces import IReporter
from pylint.reporters import BaseReporter

ModuleInfo = collections.namedtuple('ModuleInfo', ['name', 'path'])
SIMPLE_JSON = 'json'
EXTENDED_JSON = 'jsonextended'


def build_jinja_env():
    """Build Jinja2 environement"""
    env = Environment(
        loader=PackageLoader('pylint_json2html', 'templates'),
        autoescape=select_autoescape(['html', 'xml', 'jinja2']),
    )
    return env


def build_messages_metrics(messages):
    """Build reports's metrics"""
    count_types = collections.Counter(
        line.get('type') or None
        for line in messages)
    count_modules = collections.Counter(
        line.get('module') or None
        for line in messages)
    count_symbols = collections.Counter(
        line.get('symbol') or None
        for line in messages)
    count_paths = collections.Counter(
        line.get('path') or None
        for line in messages)

    return {
        'types': count_types,
        'modules': count_modules,
        'symbols': count_symbols,
        'paths': count_paths,
    }


def build_messages_modules(messages):
    """Build and yield sorted list of messages per module.

    :param list messages: List of dict of messages
    :return: Tuple of 2 values: first is the module info, second is the list
             of messages sorted by line number
    """
    data = collections.defaultdict(list)
    for line in messages:
        module_name = line.get('module')
        module_path = line.get('path')
        module_info = ModuleInfo(
            module_name,
            module_path,
        )
        data[module_info].append(line)

    for module, module_messages in data.items():
        yield (
            module,
            sorted(module_messages, key=lambda x: x.get('line')))


def stats_evaluation(stats):
    """Generate an evaluation for the given pylint ``stats``."""
    statement = stats.get('statement')
    error = stats.get('error', 0)
    warning = stats.get('warning', 0)
    refactor = stats.get('refactor', 0)
    convention = stats.get('convention', 0)

    if not statement or statement <= 0:
        return None

    malus = float(5 * error + warning + refactor + convention)
    malus_ratio = malus / statement
    return 10.0 - (malus_ratio * 10)


class Report:
    """Pylint Report Representation

    We want to represent the pylint reports in various way, structuring the raw
    data (a list of messages) into something meaningful to work with and to
    display to an end-user.
    """
    template_name = 'report.jinja2'

    def __init__(self, messages, stats=None, previous_stats=None):
        self._messages = messages
        self._module_messages = dict(build_messages_modules(messages))
        self.jinja_env = build_jinja_env()

        self.modules = sorted(
            self._module_messages.items(), key=lambda x: x[0].path)
        self.metrics = build_messages_metrics(messages)
        self.score = None
        self.previous_score = None

        if stats:
            self.score = stats_evaluation(stats)

        if previous_stats:
            self.previous_score = stats_evaluation(previous_stats)

    def get_template(self):
        """Get Jinja Template"""
        return self.jinja_env.get_template(self.template_name)

    def render(self):
        """Render report to HTML"""
        template = self.get_template()
        return template.render(
            messages=self._messages,
            metrics=self.metrics,
            report=self)


class JSONSetEncoder(json.JSONEncoder):
    """Custom JSON Encoder to transform python sets into simple list"""
    def default(self, o):  # pylint: disable=E0202
        if isinstance(o, set):
            return list(o)
        return super().default(o)


class JsonExtendedReporter(BaseReporter):
    """Extended JSON Reporter for Pylint

    Once the ``pylint_json2html`` plugin is added to pylint, this reporter
    can be used as the output format ``jsonextended``.

    It generates a JSON document with:

    * messages,
    * stats,
    * previous stats,

    For the pylint run.
    """
    __implements__ = IReporter
    name = EXTENDED_JSON
    extension = 'json'

    def __init__(self, output=None):
        super().__init__(output=output)
        self._messages = []

    def handle_message(self, msg):
        """Store new message for later use.

        .. seealso:: :meth:`~JsonExtendedReporter.on_close`
        """
        self._messages.append({
            'type': msg.category,
            'module': msg.module,
            'obj': msg.obj,
            'line': msg.line,
            'column': msg.column,
            'path': msg.path,
            'symbol': msg.symbol,
            'message': str(msg.msg) or '',
            'message-id': msg.msg_id,
        })

    def display_messages(self, layout):
        """Do nothing at the display stage"""
        pass

    def _display(self, layout):
        """Do nothing at the display stage"""
        pass

    def display_reports(self, layout):
        """Do nothing at the display stage"""
        pass

    # Event callbacks

    def on_close(self, stats, previous_stats):
        """Print the extended JSON report to reporter's output.

        :param dict stats: Metrics for the current pylint run
        :param dict previous_stats: Metrics for the previous pylint run
        """
        reports = {
            'messages': self._messages,
            'stats': stats,
            'previous': previous_stats,
        }
        print(json.dumps(reports, cls=JSONSetEncoder, indent=4), file=self.out)


def register(linter):
    """Register the reporter classes with the linter."""
    linter.register_reporter(JsonExtendedReporter)


def build_command_parser():
    """Build command parser using ``argparse`` module."""
    parser = argparse.ArgumentParser(
        description='Transform Pylint JSON report to HTML')
    parser.add_argument(
        'filename',
        metavar='FILENAME',
        type=argparse.FileType('r'),
        nargs='?',
        default=sys.stdin,
        help='Pylint JSON report input file (or stdin)')
    parser.add_argument(
        '-o', '--output',
        metavar='FILENAME',
        type=argparse.FileType('w'),
        default=sys.stdout,
        help='Pylint HTML report output file (or stdout)')
    parser.add_argument(
        '-f', '--input-format',
        metavar='FORMAT',
        choices=[SIMPLE_JSON, EXTENDED_JSON],
        action='store',
        dest='input_format',
        default='json',
        help='Pylint JSON Report input type (json or jsonextended)')

    return parser


def main():
    """Pylint JSON to HTML Main Entry Point"""
    parser = build_command_parser()
    options = parser.parse_args()
    file_pointer = options.filename
    input_format = options.input_format

    with file_pointer:
        json_data = json.load(file_pointer)

    if input_format == SIMPLE_JSON:
        report = Report(json_data)
    elif input_format == EXTENDED_JSON:
        report = Report(
            json_data.get('messages'),
            json_data.get('stats'),
            json_data.get('previous'))

    print(report.render(), file=options.output)


if __name__ == '__main__':
    main()
