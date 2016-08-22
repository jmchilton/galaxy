

found_app_main = False
current_section_desc = []
current_section_options = []


def dump_option(option):
    def print_line(line):
        print (" " * 6) + line
    if "=" not in option:
        print option
    key, default = [s.strip() for s in option.split("=", 1)]
    key = key[1:]  # strip #
    if default.isdigit():
        type = "int"
    else:
        type = "str"
    print_line("%s:" % key)
    print_line("  type: %s" % type)
    print_line("  required: false")
    print_line("  desc: |")
    for line in current_section_desc:
        print_line("    %s" % line)
    print_line("")

for line in open("config/galaxy.ini.sample", "r"):
    is_app_main = line.startswith('[app:main]')
    if not found_app_main and not is_app_main:
        continue
    if is_app_main:
        found_app_main = True
        continue

    line = line.strip()
    if not line.startswith("#"):
        for section_option in current_section_options:
            dump_option(section_option)
        current_section_desc = []
        current_section_options = []
    if line.startswith("[galaxy_amqp]"):
        break

    if line.startswith("# ") or "#" == line:
        current_section_desc.append(line[2:])
    elif line.startswith("#"):
        current_section_options.append(line)
