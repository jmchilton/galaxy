from .cwltool_deps import pathmapper
from .cwltool_deps import process


def handle_staging(generate_files, output_directory):
    generatemapper = pathmapper.PathMapper(
        [generate_files],
        output_directory,
        output_directory,
        separateDirs=False
    )

    def linkoutdir(src, tgt):
        # TODO:
        # Need to make the link to the staged file (may be inside
        # the container)
        pass
    process.stageFiles(generatemapper, linkoutdir)
