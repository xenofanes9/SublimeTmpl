#!/usr/bin/env python
# -*- coding: utf-8 -*-
# + Python 3 support
# + sublime text 3 support

import sublime
import sublime_plugin
# import sys
import io
import os
import glob
import datetime
import re

PACKAGE_NAME = 'SublimeTmpl'
TMLP_DIR = 'templates'


class MergedSettings(sublime.Settings):
    """ Helper class to merge project and plugin settings.
        Attempts to use project overrides first before defaulting back to plugin settings. """
    def __init__(self, view):
        self.global_settings = sublime.load_settings(PACKAGE_NAME + '.sublime-settings')
        self.project_settings = view.settings().get("SublimeTmpl", {})  # project overrides
     
    def get(self, name, default=None, merge=False):
        if merge and default is not None:
            # assumes we're asking for a list!
            return self.project_settings.get(name, []) + self.get_global(name, default)
        return self.project_settings.get(name, self.get_global(name, default))

    def get_global(self, name, default=None):
        return self.global_settings.get(name, default)

    def get_project(self, name, default=None):
        return self.project_settings.get(name, default)
        

def get_settings(view):
    """ Get settings object, with any project-specific overrides merged in """
    return MergedSettings(view)

def get_template_setting(template_format, settings, name, default=None, merge=False):
    """ Search for template related setting, from specific to general """
    return template_format.get(name, settings.get_project(name, settings.get_global(name, default)))

def get_attr_setting(template_format, settings):
    """ Merging attr together """
    # return {**settings.get_global('attr', {}), **settings.get_project('attr', {}), template_format.get('attr', {})}
    tmp = settings.get_global('attr', {}).copy()
    tmp.update(settings.get_project('attr', {}))
    tmp.update(template_format.get('attr', {}))
    return tmp

def get_template_locations(settings, filterBy='all'):
    """ Return all known location template locations/formats.
        If filterBy is specified, limit to specific (project) locations. """

    # first grab all valid template formats
    valid_formats = {}
    for template_format in settings.get('template_formats', [], merge=True):

        if 'id' not in template_format or 'format' not in template_format:
            print("skipping format due to missing 'id' or 'format': {0}".format(template_format))
            continue

        key = template_format.get('id')
        contents = template_format.get('format')

        if 'replace_pattern' not in contents:
            print("skipping format {0} due to missing 'replace_pattern'".format(key))
            continue

        if key not in valid_formats:          # don't overwrite a more specific format
            valid_formats[key] = contents

    # then grab all valid locations (and build dictionary of valid formats/locations)
    # Each unique path is used as a dict key for the final locations returned, i.e. {path: format}

    locations = {}
    default_location = [os.path.join(sublime.packages_path(), 'User', PACKAGE_NAME, TMLP_DIR)]
    
    if filterBy == 'project':
        candidates = settings.get_project('template_locations', [])
    else:
        candidates = settings.get('template_locations', [], merge=True)

    for location in candidates:
        if 'format' not in location:
            print("skipping location {0} due to missing 'format'".format(location))
            continue

        format_id = location.get('format')

        if format_id not in valid_formats:
            print("skipping location {0} due to unknown format {1}".format(location, format_id))
            continue 

        folders = location.get('folders', default_location)

        if not isinstance(folders, list):
            folders = [folders]     # if a single folder specified, transform to a list

        for folder in folders:
            if folder not in location:
                locations[folder] = valid_formats[format_id]

    return locations

    
def get_replace_pattern(template_format):
    """ Set replacement pattern to look for in template files """
    replace_pattern = template_format.get('replace_pattern')

    # sanity check the pattern
    try:
        x = replace_pattern % "test"
    except Exception as ex:
        sublime.message_dialog("[Warning] Replace pattern {0} doesn't seem to work: {1}".format(replace_pattern, ex))
        raise

    return replace_pattern

def get_window_variables(template_format, settings, win):
    """ Extract window and project variables, if applicable """
    if get_template_setting(template_format, settings, 'enable_project_variables', False) and hasattr(win, 'extract_variables'):
        win_variables = win.extract_variables()
        project_variables = get_template_setting(template_format, settings, 'project_variables', {})
    else:
        win_variables = {}
        project_variables = {}
    return (win_variables, project_variables)

def create_from_template(src, dest, pattern, attr, win_variables, project_variables):
    """ Use src stream to write to dest stream, replacing any template values """
    for line in src:
        for key in attr:
            line = line.replace(pattern % key, attr.get(key, ''))

        if win_variables:
            for key in project_variables:
                line = line.replace(pattern % project_variables[key], win_variables.get(key, ''))

        # keep ${var..}
        if pattern == "${%s}":
            line = re.sub(r"(?<!\\)\${(?!\d)", '\${', line)

        dest.write(line.replace('\r', '')) # replace \r\n -> \n


class SublimeTmplDirectoryCommand(sublime_plugin.WindowCommand):
    """ Run directory templates (instead of a single file) """

    class TemplateInputHandler(sublime_plugin.ListInputHandler):
        def placeholder(self):
            return "Choose template"

        def list_items(self):
            if not self.template_locations:
                sublime.message_dialog('No valid "template_folders" specified in current project file')
                return None
            project_templates = []
            for (path, template_format) in self.template_locations.items():
                if 'filename_replace_pattern' in template_format:
                    for dirpath, dirnames, filenames in os.walk(path):
                        for dirname in dirnames:
                            project_templates.append((dirname, os.path.join(dirpath, dirname)))
                        break  # don't recurse for folder templates
            return project_templates

    class NameInputHandler(sublime_plugin.TextInputHandler):
        def placeholder(self):
            return "Replace 'Name'"

    class OutputDirInputHandler(sublime_plugin.TextInputHandler):
        def placeholder(self):
            return "Output Path"

        def initial_text(self):
            # pick a sane default for destination folder
            return os.path.join(self.args.get('dirs', [''])[0], self.args.get('name', ''))

    def set_local_settings(self, filterBy='all'):
        """ Save off local settings needed by both input() handlers and run() """
        if not hasattr(self, 'settings'):
            self.settings = get_settings(self.window.active_view())

        if not hasattr(self, 'template_locations'):
            self.template_locations = get_template_locations(self.settings, filterBy)

    def input(self, args):
        """ Ensures appropriate input is provided by user for template generation """
        self.set_local_settings(args.get('filterBy'))

        if 'template' not in args:
            handler = SublimeTmplDirectoryCommand.TemplateInputHandler()
            handler.template_locations = self.template_locations
            return handler

        if 'name' not in args:
            return SublimeTmplDirectoryCommand.NameInputHandler()

        if 'output_dir' not in args:
            handler = SublimeTmplDirectoryCommand.OutputDirInputHandler()
            handler.args = args
            return handler

        return None

    def run(self, template, name, output_dir, dirs, filterBy='all'):
        """ Run directory template """
        self.set_local_settings(filterBy)
        settings = self.settings

        template_path = os.path.abspath(template)
        template_format_id = os.path.dirname(template_path)

        if template_format_id not in self.template_locations:
            print("Can't find valid template location or associated format {0}".format(template_format_id))
            print(self.template_locations)
        template_format = self.template_locations[template_format_id]

        file_pattern = template_format.get('filename_replace_pattern', '')
        file_pattern = file_pattern.replace("%s", 'name')

        # file contents setup (pull out later!)
        pattern = get_replace_pattern(template_format)
        attr = get_attr_setting(template_format, settings)
        dateformat = get_template_setting(template_format, settings, 'date_format', '%Y-%m-%d')
        attr['name'] = name
        attr['date'] = datetime.datetime.now().strftime(dateformat)
        (win_variables, project_variables) = get_window_variables(template_format, settings, self.window)

        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)

        for (dirpath, dirnames, filenames) in os.walk(template_path):
            relativepath = os.path.relpath(dirpath.replace(file_pattern, name), template_path)

            for filename in filenames:
                # copy over any files in current directory
                output_filepath = os.path.join(output_dir, relativepath, filename.replace(file_pattern, name))
                src_filepath = os.path.join(dirpath, filename)

                with open(src_filepath, 'r') as src, open(output_filepath, 'w') as dest:
                    create_from_template(src, dest, pattern, attr, win_variables, project_variables)

            for dirname in dirnames:
                # create any necessary child directories (walk() will recurse into them later)
                output_curdir = os.path.join(output_dir, dirname.replace(file_pattern, name))
                if not os.path.isdir(output_curdir):
                    os.makedirs(output_curdir)


class SublimeTmplCommand(sublime_plugin.TextCommand):

    class TemplateInputHandler(sublime_plugin.ListInputHandler):
        def placeholder(self):
            return "Choose template"

        def list_items(self):
            project_templates = []
            for (path, template_format) in self.template_locations.items():
                if 'extensions' in template_format:
                    for dirpath, dirnames, filenames in os.walk(path):
                        for filename in filenames:
                            (name, ext) = os.path.splitext(filename)
                            if ext in template_format.get('extensions'):
                                project_templates.append((filename, os.path.join(dirpath, filename)))
            return project_templates

    def set_local_settings(self, filterBy):
        """ Save off local settings needed by both input() handlers and run() """
        if not hasattr(self, 'settings'):
            self.settings = get_settings(self.view)

        if not hasattr(self, 'template_locations'):
            self.template_locations = get_template_locations(self.settings, filterBy)

    def input(self, args):
        """ Ensures appropriate input is provided by user for template generation """
        self.set_local_settings(args.get('filterBy'))

        if 'template' not in args:
            handler = SublimeTmplCommand.TemplateInputHandler()
            handler.template_locations = self.template_locations
            return handler
        return None

    def run(self, edit, template, dirs, filterBy='all'):
        """ Generate file from template """
        self.set_local_settings(filterBy)
        self.process_template(template, dirs)

    def process_template(self, template, dirs):
        """ Process selected template """
        template_path = os.path.abspath(template)
        template_format = None

        # if templates are in nested subfolders, need to walk up the chain to find template_format
        child_directory = None
        parent_directory = os.path.dirname(template_path)

        while parent_directory != child_directory:
            if parent_directory in self.template_locations:
                template_format = self.template_locations[parent_directory]
                break
            child_directory = parent_directory
            parent_directory = os.path.dirname(parent_directory)

        if not template_format:
            sublime.message_dialog('No valid templates found')
            return

        tmpl = self.get_code(template, template_format)
        tab = self.create_tab(self.view, template_format, dirs)
        
        (basefile, _) = os.path.splitext(os.path.basename(template))
        (base, ext) = os.path.splitext(basefile)
        if not ext:
            ext = base      # if no extension was provided in template name, maybe the base IS an extension?
        if ext.startswith('.'):
            ext = ext[1:]
        
        # opts = self.settings.get(type, [])
        self.set_syntax(tab, ext)
        print(tab.settings().get('syntax'))
        self.set_code(tab, tmpl)

    @staticmethod
    def is_resource_path(path):
        """ Check if an absolute path points to an ST3 resource folder """
        return os.path.commonprefix([path, sublime.packages_path()]) == sublime.packages_path()

    @staticmethod
    def format_as_resource_path(path):
        """ Convert an absolute path to an ST3 resource path """
        return os.path.join('Packages', os.path.relpath(path, sublime.packages_path()))

    def get_code(self, template, template_format):
        """ Returns template formatted code for new file """
        code = ''
        templateFound = False

        if self.is_resource_path(template):
            try:
                template = self.format_as_resource_path(template)
                code = io.StringIO(sublime.load_resource(template))
                templateFound = True
            except IOError:
                pass  # try to load as a non-resource file

        if not templateFound:
            with open(template, 'r') as fp:
                code = io.StringIO(fp.read())

        return self.format_tag(code, template_format)

    def format_tag(self, code, template_format):
        """ Replace matched patterns in file contents """
        pattern = get_replace_pattern(template_format)
        attr = get_attr_setting(template_format, self.settings)
        dateformat = get_template_setting(template_format, self.settings, 'date_format', '%Y-%m-%d')
        attr['date'] = datetime.datetime.now().strftime(dateformat)
        (win_variables, project_variables) = get_window_variables(template_format,self.settings, self.view.window())

        formatted_code = io.StringIO("")
        create_from_template(code, formatted_code, pattern, attr, win_variables, project_variables)

        return formatted_code.getvalue()

    @staticmethod
    def create_tab(view, template_format, paths=None):
        """ Create a new file to contain template output """
        if paths is None:
            paths = []
        win = view.window()
        tab = win.new_file()
        active = win.active_view()
        if len(paths) == 1:
            active.settings().set('default_dir', paths[0])

        if template_format.get('enable_file_variables_on_save', False):
            active.settings().set('tmpl_replace_pattern', get_replace_pattern(template_format))
            active.settings().set('tmpl_file_variables_on_save', template_format.get('file_variables_on_save', {}))
        return tab

    @staticmethod
    def set_code(tab, code):
        """ Insert templated contents to new file """
        tab.run_command('insert_snippet', {'contents': code})

    @staticmethod
    def set_syntax(tab, ext):
        """ Set syntax on new file """
        tab.settings().set('default_extension', ext)
        # # syntax = self.view.settings().get('syntax') # from current file
        # syntax = opts[KEY_SYNTAX] if KEY_SYNTAX in opts else ''
        # # print(syntax) # tab.set_syntax_file('Packages/Diff/Diff.tmLanguage')
        # tab.assign_syntax(syntax)


class SublimeTmplSaveFileEventListener(sublime_plugin.ViewEventListener):

    @classmethod
    def is_applicable(cls, settings):
        return settings.get('tmpl_replace_pattern') is not None

    def on_pre_save(self):
        filepath = self.view.file_name()
        filename = os.path.basename(filepath)
        settings = self.view.settings()
        pattern = settings.get('tmpl_replace_pattern')
        variables = settings.get('tmpl_file_variables_on_save', {})
        self.view.run_command('sublime_tmpl_replace', {'old': pattern.replace("%s", variables.get('saved_filepath', '')), 'new': filepath})
        self.view.run_command('sublime_tmpl_replace', {'old': pattern.replace("%s", variables.get('saved_filename', '')), 'new': filename})
        settings.erase('tmpl_replace_pattern')
        settings.erase('tmpl_file_variables_on_save')


class SublimeTmplReplaceCommand(sublime_plugin.TextCommand):
    def run(self, edit, old, new):
        region = sublime.Region(0, self.view.size())
        if region.empty() or not old or not new:
            return
        s = self.view.substr(region)
        s = s.replace(old, new)
        self.view.replace(edit, region, s)


def plugin_loaded():
    """ when first loaded, generate user template folder if it doesn't already exist """
    
    custom_path = os.path.join(sublime.packages_path(), 'User', PACKAGE_NAME, TMLP_DIR)

    tmlang = sublime.find_resources('*.tmLanguage')
    for i in tmlang:
        print(i)

    if not os.path.isdir(custom_path):
    # User folder doesn't exist to hold templates, create one and populate it with default templates
        base_path = os.path.abspath(os.path.dirname(__file__))

        if __file__.endswith("sublime-package"):
            try:
                import zipfile
                with zipfile.ZipFile(__file__, 'r') as z:
                    z.extract(TMLP_DIR, custom_path)
            except Exception as e:
                print(e)
        else:
            import shutil
            shutil.copytree(os.path.join(base_path, TMLP_DIR), custom_path)
