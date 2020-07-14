"""
Collection of classes for detecting checker disablers (like # robocop: disable) in robot files
"""
import re
from copy import copy
from collections import defaultdict


class DisablersInFile:
    def __init__(self):
        self.lastblock = -1
        self.lines = set()
        self.blocks = []

    def copy(self):
        """ Used by defaultdict to create new instance for every new key in disablers container """
        return copy(self)


class DisablersFinder:
    """ Parse all scanned file and find and disablers (in line or blocks) """
    def __init__(self, source, linter):
        self.linter = linter
        self.file_disabled = False
        self.any_disabler = False
        self.disabler_pattern = re.compile(r'robocop: (?P<disabler>disable|enable)=?(?P<rules>[\w\-,]*)')
        self.rules = defaultdict(DisablersInFile().copy)
        self._parse_file(source)

    def is_msg_disabled(self, msg):
        """
        Check if given `msg` is disabled. All takes precedence, then line disablers, then block disablers.
        We're checking for both message id and name.
        """
        if not self.any_disabler:
            return False
        if 'all' in self.rules:
            disabled = self.is_line_disabled(msg.line, 'all')
            if disabled:
                return True
        if msg.msg_id in self.rules:
            disabled = self.is_line_disabled(msg.line, msg.msg_id)
            if disabled:
                return True
        if msg.name in self.rules:
            disabled = self.is_line_disabled(msg.line, msg.name)
            if disabled:
                return True
        return False

    def is_line_disabled(self, line, rule):
        """ Helper method for is_msg_disabled that check if given line is in range of any disabled block"""
        if line in self.rules[rule].lines:
            return True
        return any(block[0] <= line <= block[1] for block in self.rules[rule].blocks)

    def _parse_file(self, source):
        try:
            with open(source, 'r') as file:
                lineno = -1
                for lineno, line in enumerate(file, start=1):
                    if '#' in line:
                        self._parse_line(line, lineno)
                self._end_block('all', lineno)
                self.file_disabled = self._is_file_disabled(lineno)
                self.any_disabler = len(self.rules) != 0
        except OSError:
            # TODO:
            pass

    def _parse_line(self, line, lineno):
        statement, comment = line.split('#', maxsplit=1)
        disabler = self.disabler_pattern.search(comment)
        if not disabler:
            return
        if not disabler.group('rules'):
            rules = ['all']
        else:
            rules = disabler.group('rules').split(',')
        block = not statement
        if disabler.group('disabler') == 'disable':
            for rule in rules:
                if block:
                    self._start_block(rule, lineno)
                else:
                    self._add_inline_disabler(rule, lineno)
        elif disabler.group('disabler') == 'enable' and block:
            for rule in rules:
                self._end_block(rule, lineno)

    def _is_file_disabled(self, last_line):
        """
        If we have open block disabler at the end of file and it starts from 0.
        It means the whole file is disabled and we can skip it in our scan.
        """
        if 'all' not in self.rules:
            return False
        if len(self.rules['all'].blocks) != 1:
            return False
        return self.rules['all'].blocks[0] == (0, last_line)

    def _add_inline_disabler(self, rule, lineno):
        self.rules[rule].lines.add(lineno)

    def _start_block(self, rule, lineno):
        if self.rules[rule].lastblock == -1:
            self.rules[rule].lastblock = lineno

    def _end_block(self, rule, lineno):
        if rule not in self.rules:
            return
        if self.rules[rule].lastblock != -1:
            block = (self.rules[rule].lastblock, lineno)
            self.rules[rule].lastblock = -1
            self.rules[rule].blocks.append(block)
        if rule == 'all':
            self._end_all_blocks(lineno)

    def _end_all_blocks(self, lineno):
        for rule in self.rules:
            if rule == 'all':
                continue  # to avoid recursion
            self._end_block(rule, lineno)