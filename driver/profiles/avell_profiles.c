// SPDX-License-Identifier: GPL-2.0-only
/* A65i: profiles, telemetry and bounded experimental fan control. */
#include <linux/acpi.h>
#include <linux/dmi.h>
#include <linux/delay.h>
#include <linux/init.h>
#include <linux/kobject.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/sysfs.h>
#include <linux/workqueue.h>
#include <linux/suspend.h>

#define EC_GUID "ABBC0F6F-8EA1-11D1-00A0-C90629100000"
static DEFINE_MUTEX(snapshot_lock);
static struct kobject *probe_kobj;
static bool boost_active, manual_dirty;

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

/* Only the three complete bytes observed with the physical button are accepted.
 * No arbitrary address or user-supplied curve/power-limit interface.
 */
static const char *profile_name(u8 value)
{
    switch (value) {
    case 0xa0: return "economy";
    case 0x20: return "balanced";
    case 0x30: return "turbo";
    default: return NULL;
    }
}

static int write_ec_internal(u16 address, u8 value)
{
    u8 input[8] = { address & 0xff, address >> 8, value, 0, 0, 0, 0, 0 };
    struct acpi_buffer in = { sizeof(input), input };
    struct acpi_buffer out = { ACPI_ALLOCATE_BUFFER, NULL };
    union acpi_object *obj;
    acpi_status status;
    int ret = -EIO;

    /* WKBC selector zero, low data byte at offset 2, as in the OEM DSDT. */
    status = wmi_evaluate_method(EC_GUID, 0, 4, &in, &out);
    obj = out.pointer;
    if (ACPI_SUCCESS(status) && obj && obj->type == ACPI_TYPE_BUFFER &&
        obj->buffer.pointer && obj->buffer.length >= 8) {
        u8 *p = obj->buffer.pointer;
        if (!(p[0] == 0xfe && p[1] == 0xfe && p[2] == 0xfe && p[3] == 0xfe))
            ret = 0;
    }
    kfree(out.pointer);
    return ret;
}

static int write_profile(u8 value)
{
    return write_ec_internal(0x0751, value);
}

static ssize_t profile_show(struct kobject *kobj, struct kobj_attribute *attr, char *buf)
{
    u8 value;
    int ret;
    const char *name;
    mutex_lock(&snapshot_lock);
    ret = read_ec(0x0751, &value);
    if (!ret && boost_active) value &= ~0x40;
    mutex_unlock(&snapshot_lock);
    if (ret)
        return ret;
    name = profile_name(value);
    return name ? sysfs_emit(buf, "%s\n", name) : -EOPNOTSUPP;
}

static ssize_t profile_store(struct kobject *kobj, struct kobj_attribute *attr,
                             const char *buf, size_t count)
{
    u8 target, before, after;
    int ret;
    if (sysfs_streq(buf, "economy")) target = 0xa0;
    else if (sysfs_streq(buf, "balanced")) target = 0x20;
    else if (sysfs_streq(buf, "turbo")) target = 0x30;
    else return -EINVAL;

    mutex_lock(&snapshot_lock);
    if (boost_active || manual_dirty) { ret = -EBUSY; goto done; }
    ret = read_ec(0x0751, &before);
    if (ret) goto done;
    if (!profile_name(before)) { ret = -EOPNOTSUPP; goto done; }
    if (before == target) goto done;
    ret = write_profile(target);
    if (ret) goto done;
    msleep(100);
    ret = read_ec(0x0751, &after);
    if (!ret && after != target) ret = -EIO;
    /* No blind retry/rollback: a physical button press may have intervened. */
done:
    mutex_unlock(&snapshot_lock);
    return ret ? ret : count;
}
static struct kobj_attribute profile_attr = __ATTR(profile, 0644, profile_show, profile_store);

/* First fan-write validation: full-fan bit only, 15-second kernel timer.
 * No duty writes and no custom-table changes. A failure leaves cooling high.
 */
static int stop_boost_locked(void)
{
    u8 mode, verify;
    int ret;
    if (!boost_active) return 0;
    ret = read_ec(0x0751, &mode);
    if (ret) return ret;
    if (mode & 0x40) {
        /* Preserve any concurrent physical profile change. */
        ret = write_profile(mode & ~0x40);
        if (ret) return ret;
        ret = read_ec(0x0751, &verify);
        if (ret) return ret;
        if (verify & 0x40) return -EIO;
    }
    boost_active = false;
    return 0;
}

static void boost_timeout(struct work_struct *work);
static DECLARE_DELAYED_WORK(boost_work, boost_timeout);
static void boost_timeout(struct work_struct *work)
{
    int ret;
    mutex_lock(&snapshot_lock);
    ret = stop_boost_locked();
    if (ret) {
        pr_err_ratelimited("avell_profiles: full-fan reset failed; retrying\n");
        schedule_delayed_work(&boost_work, HZ);
    }
    mutex_unlock(&snapshot_lock);
}

static ssize_t fan_boost_show(struct kobject *kobj, struct kobj_attribute *attr, char *buf)
{
    u8 mode;
    int ret;
    mutex_lock(&snapshot_lock);
    ret = read_ec(0x0751, &mode);
    mutex_unlock(&snapshot_lock);
    if (ret) return ret;
    return sysfs_emit(buf, "%s\n", mode & 0x40 ? "boost" : "auto");
}

static ssize_t fan_boost_store(struct kobject *kobj, struct kobj_attribute *attr,
                               const char *buf, size_t count)
{
    u8 mode, verify, flags;
    int ret;
    bool start = sysfs_streq(buf, "test");
    if (!start && !sysfs_streq(buf, "auto")) return -EINVAL;
    mutex_lock(&snapshot_lock);
    if (!start) { ret = stop_boost_locked(); goto done_boost; }
    if (boost_active || manual_dirty) { ret = -EBUSY; goto done_boost; }
    ret = read_ec(0x0751, &mode);
    if (ret) goto done_boost;
    if (!profile_name(mode)) { ret = -EOPNOTSUPP; goto done_boost; }
    ret = read_ec(0x07c6, &flags);
    if (ret) goto done_boost;
    if (flags & 4) { ret = -EBUSY; goto done_boost; }
    /* Arm before writing, including a write whose acknowledgement is lost. */
    boost_active = true;
    mod_delayed_work(system_wq, &boost_work, 15 * HZ);
    ret = write_profile(mode | 0x40);
    if (!ret) ret = read_ec(0x0751, &verify);
    if (!ret && !(verify & 0x40)) ret = -EIO;
    if (ret) stop_boost_locked();
done_boost:
    mutex_unlock(&snapshot_lock);
    return ret ? ret : count;
}
static struct kobj_attribute fan_boost_attr = __ATTR(fan_boost, 0644, fan_boost_show, fan_boost_store);

#include "fan_manual.h"

static int boost_pm_event(struct notifier_block *nb, unsigned long action, void *unused)
{
    int ret = 0;
    if (action == PM_SUSPEND_PREPARE || action == PM_HIBERNATION_PREPARE ||
        action == PM_RESTORE_PREPARE) {
        mutex_lock(&snapshot_lock);
        ret = stop_manual_locked();
        if (!ret) ret = stop_boost_locked();
        mutex_unlock(&snapshot_lock);
    }
    return ret ? NOTIFY_BAD : NOTIFY_OK;
}
static struct notifier_block boost_pm = { .notifier_call = boost_pm_event };

/* OEM ECSpec byte order. Retry torn two-byte tachometer samples. */
static int read_rpm(u16 high_addr, u16 low_addr, unsigned int *rpm)
{
    u8 high, low, verify;
    int attempt, ret;
    for (attempt = 0; attempt < 3; attempt++) {
        ret = read_ec(high_addr, &high);
        if (ret) return ret;
        ret = read_ec(low_addr, &low);
        if (ret) return ret;
        ret = read_ec(high_addr, &verify);
        if (ret) return ret;
        if (high == verify) {
            *rpm = ((unsigned int)high << 8) | low;
            return *rpm <= 15000 ? 0 : -ERANGE;
        }
    }
    return -EAGAIN;
}

static ssize_t fans_show(struct kobject *kobj, struct kobj_attribute *attr, char *buf)
{
    unsigned int fan1, fan2;
    u8 cpu, gpu, duty1, duty2, host, flag0, flag1, target0, target1;
    int ret;
    mutex_lock(&snapshot_lock);
    ret = read_rpm(0x0464, 0x0465, &fan1);
    if (!ret) ret = read_rpm(0x046c, 0x046b, &fan2);
    if (!ret) ret = read_ec(0x043e, &cpu);
    if (!ret) ret = read_ec(0x044f, &gpu);
    if (!ret) ret = read_ec(0x1804, &duty1);
    if (!ret) ret = read_ec(0x1809, &duty2);
    if (!ret) ret = read_ec(0x0741, &host);
    if (!ret) ret = read_ec(0x07c5, &flag0);
    if (!ret) ret = read_ec(0x07c6, &flag1);
    if (!ret) ret = read_ec(0x0f20, &target0);
    if (!ret) ret = read_ec(0x0f50, &target1);
    mutex_unlock(&snapshot_lock);
    if (ret) return ret;
    return sysfs_emit(buf, "{\"fan1_rpm\":%u,\"fan2_rpm\":%u,\"cpu\":%u,\"gpu\":%u,\"duty1_raw\":%u,\"duty2_raw\":%u,\"host_0741\":%u,\"flags_07c5\":%u,\"flags_07c6\":%u,\"target1_raw\":%u,\"target2_raw\":%u}\n",
                      fan1, fan2, cpu, gpu, duty1, duty2, host, flag0, flag1, target0, target1);
}
static struct kobj_attribute fans_attr = __ATTR(fans, 0444, fans_show, NULL);

/* Fixed addresses only. Capture before implementing any fan-table writes. */
static ssize_t fan_config_show(struct kobject *kobj, struct kobj_attribute *attr, char *buf)
{
    u8 table[96], flags0, flags1, features, mode, host;
    int ret, i;
    ssize_t length;
    mutex_lock(&snapshot_lock);
    if (manual_dirty) { mutex_unlock(&snapshot_lock); return -EBUSY; }
    ret = read_ec(0x07c5, &flags0);
    if (!ret) ret = read_ec(0x07c6, &flags1);
    if (!ret) ret = read_ec(0x078e, &features);
    if (!ret) ret = read_ec(0x0751, &mode);
    if (!ret) ret = read_ec(0x0741, &host);
    for (i = 0; !ret && i < ARRAY_SIZE(table); i++)
        ret = read_ec(0x0f00 + i, &table[i]);
    mutex_unlock(&snapshot_lock);
    if (ret) return ret;
    length = sysfs_emit(buf, "{\"read_only\":true,\"flags_07c5\":%u,\"flags_07c6\":%u,\"features_078e\":%u,\"mode_0751\":%u,\"host_0741\":%u,\"table_0f00_0f5f\":[",
                        flags0, flags1, features, mode, host);
    for (i = 0; i < ARRAY_SIZE(table); i++)
        length += sysfs_emit_at(buf, length, "%s%u", i ? "," : "", table[i]);
    length += sysfs_emit_at(buf, length, "]}\n");
    return length;
}
static struct kobj_attribute fan_config_attr = __ATTR(fan_config, 0444, fan_config_show, NULL);
static struct attribute *avell_attrs[] = {
    &profile_attr.attr, &fans_attr.attr, &fan_config_attr.attr, &fan_boost_attr.attr, &fan_control_attr.attr, NULL
};
static const struct attribute_group avell_group = { .attrs = avell_attrs };

static bool exact_dmi(int field, const char *expected)
{
	const char *value = dmi_get_system_info(field);
	return value && !strcmp(value, expected);
}

static int __init avell_profiles_init(void)
{
	int ret;
	if (!exact_dmi(DMI_SYS_VENDOR, "Avell") ||
	    !exact_dmi(DMI_PRODUCT_NAME, "A65i") ||
	    !exact_dmi(DMI_BOARD_NAME, "ION A65i") ||
	    !exact_dmi(DMI_BIOS_VERSION, "N.1.09AVE03"))
		return -ENODEV;
	if (!wmi_has_guid(EC_GUID))
		return -ENODEV;
	probe_kobj = kobject_create_and_add("avell_profiles", kernel_kobj);
	if (!probe_kobj)
		return -ENOMEM;
	ret = register_pm_notifier(&boost_pm);
	if (ret) { kobject_put(probe_kobj); return ret; }
	ret = sysfs_create_group(probe_kobj, &avell_group);
	if (ret) {
		unregister_pm_notifier(&boost_pm);
		kobject_put(probe_kobj);
	}
	return ret;
}

static void __exit avell_profiles_exit(void)
{
	sysfs_remove_group(probe_kobj, &avell_group);
	unregister_pm_notifier(&boost_pm);
	cancel_delayed_work_sync(&boost_work);
	cancel_delayed_work_sync(&manual_work);
	mutex_lock(&snapshot_lock);
	if (stop_manual_locked())
		pr_err("avell_profiles: manual restore failed on unload\n");
	if (stop_boost_locked())
		pr_err("avell_profiles: reset failed on unload; full fan may remain active\n");
	mutex_unlock(&snapshot_lock);
	kobject_put(probe_kobj);
}

module_init(avell_profiles_init);
module_exit(avell_profiles_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Avell A65i restricted firmware performance profiles");
