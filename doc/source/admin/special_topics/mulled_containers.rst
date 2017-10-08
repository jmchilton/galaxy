================================
Containers for Tool Dependencies
================================

Galaxy tools (also called wrappers) are able to use Conda packages
(see more information in our `Galaxy Conda documentation`_) and Docker containers
as dependency resolvers. The IUC_ recommends to use Conda packages as primary dependency
resolver for tool development, mainly because Docker is not available on every (HPC-) system
and Conda can be installed by Galaxy and maintained entirely in user-space so this allows
maximum portability of a Galaxy tool. Nevertheless, Docker and other container technologies
have many important features including an additional level of reproducibility if they are available 
for a deployment. Many deployments will therefore wish to run Galaxy tools via containers and
this document describes how to do that - in broad strokes at least.

Since 2014 Galaxy has supported running tools in Docker containers via a special
`container annotation`_ inside of the ``requirements`` field.

.. code-block:: xml

    <requirements>
        <!-- Container based dependency handling -->
        <container type="docker">busybox:ubuntu-14.04</container>
        <!-- Conda based dependency handling -->
        <requirement type="package" version="8.22">gnu_coreutils</requirement>
    </requirements>


While explicit annotation of containers this way is popular in other platforms, this approach
falls short of the Galaxy ideals of transparency and reproduciblity and have practical limitations
all of which has slowed down the adoption by Galaxy tool developers.

At a very basic level, the blackbox nature of Docker and other container technologies such as
Singularity conflict with Galaxy's mantra of transparency. Conda packages can be traced back to
Conda recipes describing how the package was built and this is an important part of providing a
transparent view of an analysis conducted with these tools. Additionally, there will be enviorments
where Docker and/or Singluarity is not available - so describig tool dependencies with Conda 
packages ensures maximum reproducibility. 

Therefore, if every tool should define best practice packages also having to define containers is
both extra work (every tool needs to be annotated with a container name (as shown above) and this 
container needs to be created beforehand, usually manually) and introduces the very real possibility
the target container is configured in a way different than the Conda packages would be (the 
container might use different software sources, compilation options, dependencies, etc.).

Not an ideal solution and something we wanted to solve.

Here we demonstrate a solution that can create Containers from Conda packages automatically.
This can be either used to support communities like BioContainers_ to create containers
before deploying a Galaxy tool or this can be used by Galaxy to create containers on-demand and 
on-the-fly if one is not available already.

This work is built on the mulled toolkit described here `TODO <>`__.

.. _Galaxy Conda documentation: ../conda_faq.rst
.. _IUC: https://galaxyproject.org/iuc/
.. _container annotation:  https://github.com/galaxyproject/galaxy/blob/dev/test/functional/tools/catDocker.xml#L4
.. _BioContainers: https://github.com/biocontainers
.. _bioconda: https://github.com/bioconda/bioconda-recipes
.. _BioContainers Quay.io account: https://quay.io/organization/biocontainers
.. _galaxy-lib: https://github.com/galaxyproject/galaxy-lib
