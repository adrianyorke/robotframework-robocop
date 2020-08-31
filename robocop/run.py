"""
Main class of Robocop module. Gather files for scan, checkers and parse cli arguments and scan files.
"""
import sys
from pathlib import Path
from robot.api import get_model
from robocop import checkers
from robocop.config import Config
from robocop import reports
from robocop.utils import DisablersFinder, FileType, FileTypeChecker, RobotFile
from robocop.checkers.errors import ParsingErrorChecker
import robocop.exceptions


class Robocop:
    def __init__(self, from_cli=False):
        self.checkers = []
        self.out = sys.stdout
        self.rules = {}
        self.reports = []
        self.disabler = None
        self.config = Config()
        if from_cli:
            self.config.parse_opts()
        self.set_output()
        self.load_checkers()
        self.list_checkers()
        self.load_reports()
        self.configure_checkers_or_reports()

    def set_output(self):
        """ Set output for printing to file if configured. Else use standard output """
        self.out = self.config.output or sys.stdout

    def write_line(self, line):
        """ Print line using file=self.out parameter (set in `set_output` method) """
        print(line, file=self.out)

    def run(self):
        """ Entry point for running scans """
        self.run_checks()
        self.make_reports()
        if not self.out.closed:
            self.out.close()
        for report in self.reports:
            if report.name == 'return_status':
                sys.exit(report.return_status)

    def recognize_file_type(self, file_type_checker, file, files):
        """
        Pre-parse file to recognize its type. If the filename is `__init__.*`, the type is `INIT`.
        Files with .resource extension are 'RESOURCE' type.
        If the file is imported somewhere then file type is `RESOURCE`. Otherwise file type is `GENERAL`.
        These types are important since they are used to define parsing class for robot API.
        """
        if '__init__' in file.source.name:
            file.type = FileType.INIT
        elif file.source.suffix.lower() == '.resource':
            file.type = FileType.RESOURCE
        else:
            file.type = FileType.GENERAL
        files[file.source] = file
        file_type_checker.source = file.source
        model = get_model(file.source)
        file_type_checker.visit(model)
        return files

    def run_checks(self):
        if not self.config.paths:
            print('No path has been provided')
            sys.exit()
        files = {file: RobotFile(file) for file in self.get_files(self.config.paths, self.config.recursive)}
        file_type_checker = FileTypeChecker(files, self.config.exec_dir)
        parsed_files = {}
        for file, robot_file in files.items():
            self.register_disablers(file)
            if self.disabler.file_disabled:
                continue
            files = self.recognize_file_type(file_type_checker, robot_file, files)
            robot_file = files[file]
            robot_file.scanned_with_type = robot_file.type
            parsed_files[file] = robot_file
            model = robot_file.type.get_parser()(str(file))
            for checker in self.checkers:
                if checker.disabled:
                    continue
                checker.source = str(file)
                checker.scan_file(model)
        self.run_checks_on_files_with_type_changed(parsed_files)

    def run_checks_on_files_with_type_changed(self, files):
        for checker in self.checkers:
            if isinstance(checker, ParsingErrorChecker):
                for file, robot_file in files.items():
                    if robot_file.scanned_with_type == robot_file.type:
                        continue
                    model = robot_file.type.get_parser()(str(file))
                    checker.parse_only_section_not_allowed = True
                    checker.source = file
                    checker.scan_file(model)
                break

    def register_disablers(self, file):
        """ Parse content of file to find any disabler statements like # robocop: disable=rulename """
        self.disabler = DisablersFinder(file, self)

    def report(self, rule_msg):
        if not rule_msg.enabled:  # disabled from cli
            return
        if self.disabler.is_rule_disabled(rule_msg):  # disabled from source code
            return
        for report in self.reports:
            report.add_message(rule_msg)
        self.log_message(source=rule_msg.source,
                         line=rule_msg.line,
                         col=rule_msg.col,
                         severity=rule_msg.severity.value,
                         rule_id=rule_msg.rule_id,
                         desc=rule_msg.desc,
                         msg_name=rule_msg.name)

    def log_message(self, **kwargs):
        self.write_line(self.config.format.format(**kwargs))

    def load_checkers(self):
        checkers.init(self)

    def list_checkers(self):
        if self.config.list:
            rule_by_id = {msg.rule_id: msg for checker in self.checkers for msg in checker.rules_map.values()}
            rule_ids = sorted([key for key in rule_by_id])
            for rule_id in rule_ids:
                print(rule_by_id[rule_id])
            sys.exit()

    def load_reports(self):
        reports.register(self)

    def register_checker(self, checker):
        if not self.any_rule_enabled(checker):
            checker.disabled = True
        for rule_name, rule in checker.rules_map.items():
            if rule_name in self.rules:
                (_, checker_prev) = self.rules[rule_name]
                raise robocop.exceptions.DuplicatedRuleError('name', rule_name, checker, checker_prev)
            if rule.rule_id in self.rules:
                (_, checker_prev) = self.rules[rule.rule_id]
                raise robocop.exceptions.DuplicatedRuleError('id', rule.rule_id, checker, checker_prev)
            self.rules[rule_name] = (rule, checker)
            self.rules[rule.rule_id] = (rule, checker)
        self.checkers.append(checker)

    def register_report(self, report):
        if report.name in self.config.reports:
            self.reports.append(report)

    def make_reports(self):
        for report in self.reports:
            output = report.get_report()
            if output is not None:
                self.write_line(output)

    def get_files(self, files_or_dirs, recursive):
        for file in files_or_dirs:
            yield from self.get_absolute_path(Path(file), recursive)

    def get_absolute_path(self, path, recursive):
        if not path.exists():
            raise robocop.exceptions.FileError(path)
        if path.is_file():
            if self.should_parse(path):
                yield path.absolute()
        elif path.is_dir():
            for file in path.iterdir():
                if file.is_dir() and not recursive:
                    continue
                yield from self.get_absolute_path(file, recursive)

    def should_parse(self, file):
        """ Check if file extension is in list of supported file types (can be configured from cli) """
        return file.suffix and file.suffix.lower() in self.config.filetypes

    def any_rule_enabled(self, checker):
        for name, rule in checker.rules_map.items():
            rule.enabled = self.config.is_rule_enabled(rule)
            checker.rules_map[name] = rule
        return any(msg.enabled for msg in checker.rules_map.values())

    def configure_checkers_or_reports(self):
        for config in self.config.configure:
            if config.count(':') < 2:
                raise robocop.exceptions.ConfigGeneralError(
                    f'Provided invalid config: \'{config}\' (general pattern: <rule>:<param>:<value>)')
            rule_or_report, param, value, *values = config.split(':')
            if rule_or_report in self.rules:
                msg, checker = self.rules[rule_or_report]
                if param == 'severity':
                    self.rules[rule_or_report] = (msg.change_severity(value), checker)
                else:
                    configurable = msg.get_configurable(param)
                    if configurable is None:
                        raise robocop.exceptions.ConfigGeneralError(
                            f'Provided param \'{param}\' for rule \'{rule_or_report}\' does not exists')
                    checker.configure(configurable[1], configurable[2](value))
            elif any(rule_or_report == report.name for report in self.reports):
                for report in self.reports:
                    if report.name == rule_or_report:
                        report.configure(param, value, *values)
            else:
                raise robocop.exceptions.ConfigGeneralError(
                    f'Provided rule or report \'{rule_or_report}\' does not exists')


def run_robocop():
    linter = Robocop(from_cli=True)
    linter.run()
