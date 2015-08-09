#OpenStack CVRM README

CVRM is an Attribute-based Constraint Specification and Enfrocement mechanism for virtual resource orchestration in OpenStack. 
The project is built on DevStack and is in beta stage. The master branch is in version 0.20. It provides  REST API  to specify mandatory constaints for attaching storages to virtual machines. 

#Build

CVRM is developed in OpenStack Icehouse (However, it can easily incorporate to later versions(Kilo or Juno).

The build process is as follows:
* Get it from git

```
    git clone https://github.com/kbijon/OpenStack-CVRM.git
```
* Rename the directory to stack:
```
    mv -r OpenStack-CVRM stack
```

*  Move the directory to /opt
```
    mv -r stack /opt/
```
*  Get into the devstack  in side stack
```
    cd /opt/stack/devstack
```
*  Run stach.sh 
```
    ./stack.sh
```

#Usage

It provides APIs for managing  attributes and  their values and for assigning the attributes to VM and Storages.

The VM attributes APIs:

*  Create an attribute

``` 
nova att-create --name color
```

*  Delete an attribute

```
 nova att-delete --name color
```


*  List attributes

```
 nova att-list 
```

*  Create an attribute value

```
 nova att-value-set --name color --value red
```   

*  Delete an attribute value

```
 nova att-value-delete --name color --value red
```
 
*  List values of an attribute

```
 nova att-value-list --name color
```

The storage attributes APIs:

*  Create an attribute

``` 
cinder att-create --name color
```

*  Delete an attribute

```
 cinder att-delete --name color
```


*  List attributes

```
 cinder att-list 
```

*  Create an attribute value

```
 cinder att-value-set --name color --value red
```   

*  Delete an attribute value

```
 cinder att-value-delete --name color --value red
```
 
*  List values of an attribute

```
cinder  att-value-list --name color
```

#References

Please refer to/cite the following paper.

1. [Virtual Resource Orchestration Constraints in Cloud Infrastructure as a Service](http://profsandhu.com/confrnc/misconf/p183-bijon.pdf), Khalid Bijon, Ram Krishnan, and Ravi Sandhu.In Proceedings of the 5th ACM Conference on Data and Application Security and Privacy (CODASPY), March 2-4, 2015, San Antonio, Texas, pages 183-194.
