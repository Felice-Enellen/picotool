import os
import time
from datetime import datetime
from argparse import Namespace

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from . import debounce
from .. import util
from ..game import game
from ..lua import lua


def do_build(args):
    """Executor for the p8tool build command.

    Args:
        args: The argparse.Namespace arguments object.
    """
    if (not args.filename.endswith('.p8') and
            not args.filename.endswith('.p8.png')):
        util.error('Output filename must end with .p8 or .p8.png.')
        return 1

    empty_source = game.Game.make_empty_game(filename=args.filename)

    # Determine whether output file exists and if so load it, otherwise
    # create an empty cart.
    if os.path.exists(args.filename):
        result = game.Game.from_filename(args.filename)
    else:
        result = game.Game.make_empty_game(filename=args.filename)

    for section in ('lua', 'gfx', 'gff', 'map', 'sfx', 'music'):
        if getattr(args, section, None) is not None:

            # Verify "empty" overrides don't conflict with provided sources.
            if getattr(args, 'empty_' + section, False):
                util.error('Cannot specify --%s and --empty-%s args '
                           'together.' % (section, section))
                return 1

            # Verify source files exist and are of supported types.
            fn = getattr(args, section)
            if not os.path.exists(fn):
                util.error('File "%s" given for --%s arg does not exist.' %
                           (fn, section))
                return 1
            # TODO: support .png files as gfx source
            if (not fn.endswith('.p8') and
                    not fn.endswith('.p8.png') and
                    not (section == 'lua' and fn.endswith('.lua'))):
                util.error(
                    'Unsupported file type for --%s arg.' % (section,))
                return 1

            # Load section from source and store it in the result.
            # TODO: support .png files as gfx source
            if section == 'lua' and fn.endswith('.lua'):
                with open(fn, 'rb') as infh:
                    infh = expand_requirements([line for line in infh], [fn])
                    result.lua = lua.Lua.from_lines(
                        infh, version=game.DEFAULT_VERSION)
            else:
                source = game.Game.from_filename(fn)
                setattr(result, section, getattr(source, section))

        elif getattr(args, 'empty_' + section, False):
            setattr(result, section, getattr(empty_source, section))

    # Save result as args.filename.
    # TODO: allow overriding the label source for .p8.png
    result.to_file(filename=args.filename)

    if getattr(args, 'watch', False):
        # create the handler & observer
        handler = BuildHandler(strip_watch_arg(args))
        observer = Observer()
        observer.schedule(handler, './', recursive=True)
        observer.start()
        print('Watching for changes...')

        # allow the observer to run indefinitely (until Ctrl-C)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()

        # wait until the thread terminates
        observer.join()

    return 0


def expand_requirements(lines, paths, from_line=0):
    line_num = from_line
    while line_num < len(lines):
        line = lines[line_num]
        match = lua.Lua.REQUIRE_REGEX.search(line.decode("utf-8"))
        if match:
            path = match.groupdict().get('path')
            del lines[line_num]
            if path not in paths:
                # load the file content
                paths.append(path)
                with open(path, 'rb') as dependency:
                    lines[line_num:line_num] = [dep_line for dep_line in dependency]
        else:
            line_num += 1
    return lines


def strip_watch_arg(args):
    arg_vals = vars(args)
    del arg_vals["watch"]
    return Namespace(**arg_vals)


class BuildHandler(FileSystemEventHandler):
    def __init__(self, build_args):
        self.build_args = build_args
        self.path = os.path.normpath(build_args.filename)
        super(BuildHandler, self).__init__()

    def on_any_event(self, event):
        if os.path.normpath(event.src_path) != self.path:
            self.do_debounced_build()

    @debounce(1)
    def do_debounced_build(self):
        print("<{}> Changes detected, rebuilding {}".format(
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'), self.path))
        do_build(self.build_args)
