obj-m += avell_profiles.o
KDIR ?= /lib/modules/$(shell uname -r)/build
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) W=1 modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
