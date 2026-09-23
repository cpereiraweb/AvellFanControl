// SPDX-License-Identifier: GPL-2.0-only
/* A65i N.1.09AVE03: fixed read-only EC snapshot, no register-write API.
 * Transport verified against this machine's DSDT: _SB.AMW0.WMBC(0,4,buf),
 * OEMG selects RKBC when bytes 4..7 equal 0x100 (byte 5 = 1).
 * EC RAM addresses are from OEM ECSpec and Uniwill's published interface.
 */
#include <linux/acpi.h>
#include <linux/dmi.h>
#include <linux/init.h>
#include <linux/kobject.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/sysfs.h>

#define EC_GUID "ABBC0F6F-8EA1-11D1-00A0-C90629100000"
static DEFINE_MUTEX(snapshot_lock);
static struct kobject *probe_kobj;

static const struct {
	const char *name;
	u16 address;
} registers[] = {
	{ "cpu_temperature", 0x043e },
	{ "gpu_temperature", 0x044f },
	{ "fan1_byte1", 0x0464 },
	{ "fan1_byte2", 0x0465 },
	{ "fan2_byte1", 0x046c },
	{ "fan2_byte2", 0x046b },
	{ "project_id", 0x0740 },
	{ "oem_app_flags", 0x0741 },
	{ "fan_mode", 0x0751 },
	{ "custom_profile_flags", 0x0727 },
	{ "mode_index", 0x07ab },
	{ "fan_duty_left", 0x075b },
	{ "fan_duty_right", 0x075c },
	{ "fan_features", 0x078e },
	{ "fan1_raw", 0x1804 },
	{ "fan2_raw", 0x1809 },
};

static int read_ec(u16 address, u8 *value)
{
	u8 input[8] = { 0 };
	struct acpi_buffer in = { sizeof(input), input };
	struct acpi_buffer out = { ACPI_ALLOCATE_BUFFER, NULL };
	union acpi_object *obj;
	acpi_status status;
	int ret = -EIO;

	input[0] = address & 0xff;
	input[1] = address >> 8;
	input[5] = 1; /* READ, fixed; never expose the write selector. */
	status = wmi_evaluate_method(EC_GUID, 0, 4, &in, &out);
	obj = out.pointer;
	if (ACPI_SUCCESS(status) && obj && obj->type == ACPI_TYPE_BUFFER &&
	    obj->buffer.pointer && obj->buffer.length >= 8) {
		u8 *p = obj->buffer.pointer;
		/* Firmware uses repeated FE bytes to signal busy/timeout. */
		if (!(p[0] == 0xfe && p[1] == 0xfe && p[2] == 0xfe && p[3] == 0xfe)) {
			*value = p[0];
			ret = 0;
		}
	}
	kfree(out.pointer);
	return ret;
}

static ssize_t snapshot_show(struct kobject *kobj, struct kobj_attribute *attr,
			     char *buf)
{
	u8 values[ARRAY_SIZE(registers)];
	size_t i;
	ssize_t length = 0;
	int ret = 0;

	mutex_lock(&snapshot_lock);
	for (i = 0; i < ARRAY_SIZE(registers); i++) {
		ret = read_ec(registers[i].address, &values[i]);
		if (ret)
			break;
	}
	mutex_unlock(&snapshot_lock);
	if (ret)
		return ret; /* Never return fabricated zero readings after a failure. */
	length += sysfs_emit_at(buf, length, "{\"read_only\":true,\"raw\":{");
	for (i = 0; i < ARRAY_SIZE(registers); i++)
		length += sysfs_emit_at(buf, length, "%s\"%s\":%u",
				       i ? "," : "", registers[i].name, values[i]);
	length += sysfs_emit_at(buf, length, "}}\n");
	return length;
}

static struct kobj_attribute snapshot_attr = __ATTR(snapshot, 0400, snapshot_show, NULL);

static bool exact_dmi(int field, const char *expected)
{
	const char *value = dmi_get_system_info(field);
	return value && !strcmp(value, expected);
}

static int __init avell_probe_init(void)
{
	int ret;
	if (!exact_dmi(DMI_SYS_VENDOR, "Avell") ||
	    !exact_dmi(DMI_PRODUCT_NAME, "A65i") ||
	    !exact_dmi(DMI_BOARD_NAME, "ION A65i") ||
	    !exact_dmi(DMI_BIOS_VERSION, "N.1.09AVE03"))
		return -ENODEV;
	if (!wmi_has_guid(EC_GUID))
		return -ENODEV;
	probe_kobj = kobject_create_and_add("avell_ec_probe", kernel_kobj);
	if (!probe_kobj)
		return -ENOMEM;
	ret = sysfs_create_file(probe_kobj, &snapshot_attr.attr);
	if (ret)
		kobject_put(probe_kobj);
	return ret;
}

static void __exit avell_probe_exit(void)
{
	sysfs_remove_file(probe_kobj, &snapshot_attr.attr);
	kobject_put(probe_kobj);
}

module_init(avell_probe_init);
module_exit(avell_probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Avell A65i fixed read-only EC diagnostic snapshot");
