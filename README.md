OpenStack CVRM README

CVRM is an Attribute-based Constraint Specification and Enfrocement mechanism for virtual resource orchestration in OpenStack. 
The project is built on DevStack and is in beta stage. The master branch is in version 0.20. It provides  REST API  to specify mandatory constaints for attaching storages to virtual machines. 

Build

CVRM is developed in OpenStack Icehouse (However, it can easily incorporate to later versions(Kilo or Juno).

The build process is as follows:

1. Get it from git (git clone https://github.com/kbijon/OpenStack-CVRM.git)
2. Rename the directory to stack 
3. Move the directory to /opt
4. cd to stack/devstack
5. ./stack.sh


Usage

It provides APIs for managing  attributes and  their values and for assigning the attributes to VM and Storages.

The VM attributes APIS:

1. Create an attribute: nova att-create --name color
2. Delete an attribute: nova att-delete --name color
3. List attributes: nova att-list 
4. Create an attribute value: nova att-value-set --name color --value red
5. Delete an attribute value: nova att-value-delete --name color --value red
6. List values of an attribute: nova att-value-list --name color


References

Please refer to/cite the following papers based on the scheduler you are using: the former for SEBF and the latter for DARK.

    Efficient Coflow Scheduling with Varys, Mosharaf Chowdhury, Yuan Zhong, Ion Stoica, ACM SIGCOMM, 2014.
    Efficient Coflow Scheduling Without Prior Knowledge, Mosharaf Chowdhury, Ion Stoica, ACM SIGCOMM, 2015.

