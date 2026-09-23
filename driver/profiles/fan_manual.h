/* SPDX-License-Identifier: GPL-2.0-only */
/* Limited experimental duty control. Included after the EC transport.
 * All functions with _locked require snapshot_lock. No arbitrary EC ABI.
 */
static u8 saved_table[96], manual_profile, saved_oem;
static bool table_dirty[96], manual_running, manual_emergency;
static unsigned int manual_percent, manual_id;
static unsigned long manual_deadline, manual_started;
static const char *manual_reason = "ready";
static void manual_watchdog(struct work_struct *work);
static DECLARE_DELAYED_WORK(manual_work, manual_watchdog);

static int write_fan_ec(u16 addr, u8 value)
{
    /* Private whitelist in addition to the closed sysfs command vocabulary. */
    if (!((addr >= 0x0f00 && addr <= 0x0f5f) || addr == 0x07c5 ||
          addr == 0x07c6 || addr == 0x0741 || addr == 0x1804 || addr == 0x1809))
        return -EINVAL;
    return write_ec_internal(addr, value);
}

static int checked_fan_write(u16 addr, u8 value)
{
    u8 actual;
    int ret = write_fan_ec(addr, value);
    if (!ret) ret = read_ec(addr, &actual);
    return ret ? ret : actual == value ? 0 : -EIO;
}

static int set_fan_bits(u16 addr, u8 mask, u8 bits)
{
    u8 value, target;
    int ret = read_ec(addr, &value);
    if (ret) return ret;
    target = (value & ~mask) | (bits & mask);
    return target == value ? 0 : checked_fan_write(addr, target);
}

static void emergency_fans_locked(void)
{
    u8 mode;
    if (!read_ec(0x0751, &mode)) {
        if (!(mode & 0x40)) {
            manual_emergency = true; /* Including a lost acknowledgement. */
            if (write_profile(mode | 0x40))
                pr_err_ratelimited("avell_profiles: emergency full-fan command failed\n");
        }
    }
}

static int stop_manual_locked(void)
{
    int ret, i;
    u8 mode, verify;
    if (!manual_dirty) return 0;
    manual_running = false;
    /* Disable custom tables BEFORE restoring entries, never activate a partial table. */
    ret = set_fan_bits(0x07c6, 4, 0);
    if (ret) { emergency_fans_locked(); return ret; }
    ret = set_fan_bits(0x0741, 1, saved_oem & 1);
    if (ret) return ret;
    ret = set_fan_bits(0x07c5, 0x80, 0);
    if (ret) return ret;
    for (i = 0; i < 96; i++) {
        if (!table_dirty[i]) continue;
        ret = checked_fan_write(0x0f00 + i, saved_table[i]);
        if (ret) return ret;
        table_dirty[i] = false;
    }
    if (manual_emergency) {
        ret = read_ec(0x0751, &mode);
        if (ret) return ret;
        ret = write_profile(mode & ~0x40);
        if (ret) return ret;
        ret = read_ec(0x0751, &verify);
        if (ret) return ret;
        if (verify & 0x40) return -EIO;
        manual_emergency = false;
    }
    manual_dirty = false;
    manual_percent = 0;
    module_put(THIS_MODULE); /* Keep code and saved table alive until restored. */
    return 0;
}

static int manual_health_locked(void)
{
    u8 cpu, gpu, mode, flags0, flags1, host, duty0, duty1;
    int ret = read_ec(0x043e, &cpu);
    if (!ret) ret = read_ec(0x044f, &gpu);
    if (!ret) ret = read_ec(0x0751, &mode);
    if (ret) return ret;
    if (cpu == 0 || gpu == 0 || cpu >= 85 || gpu >= 80) return -ERANGE;
    if (mode != manual_profile) return -EAGAIN;
    if (manual_running) {
        ret = read_ec(0x0741, &host);
        if (!ret) ret = read_ec(0x07c5, &flags0);
        if (!ret) ret = read_ec(0x07c6, &flags1);
        if (ret) return ret;
        if (!(host & 1) || !(flags0 & 0x80) || !(flags1 & 4)) return -EREMOTEIO;
        /* Five seconds for initial settling; never reassert over a firmware override. */
        if (time_after_eq(jiffies, manual_started + 5 * HZ)) {
            ret = read_ec(0x1804, &duty0);
            if (!ret) ret = read_ec(0x1809, &duty1);
            if (ret) return ret;
            if (abs((int)duty0 - (int)manual_percent * 2) > 10 ||
                abs((int)duty1 - (int)manual_percent * 2) > 10) return -EREMOTEIO;
        }
    }
    return 0;
}

static void manual_watchdog(struct work_struct *work)
{
    int ret = 0;
    mutex_lock(&snapshot_lock);
    if (manual_running) {
        ret = manual_health_locked();
        if (ret || time_after_eq(jiffies, manual_deadline)) {
            manual_reason = ret == -EREMOTEIO ? "firmware_override" :
                ret ? "temperature_sensor_or_profile" : "timeout";
            manual_running = false;
        }
    }
    if (manual_dirty && !manual_running) ret = stop_manual_locked();
    if (ret && manual_dirty)
        pr_err_ratelimited("avell_profiles: manual restore incomplete, retrying\n");
    if (manual_dirty) schedule_delayed_work(&manual_work, HZ);
    mutex_unlock(&snapshot_lock);
}

static int start_manual_locked(unsigned int percent)
{
    u8 features, flag0, flag1, desired[96];
    int ret, i, fan, offset, limit;
    if (percent < 50 || percent > 100 || percent % 5) return -EINVAL;
    if (manual_dirty || boost_active) return -EBUSY;
    ret = read_ec(0x078e, &features);
    if (!ret) ret = read_ec(0x07c5, &flag0);
    if (!ret) ret = read_ec(0x07c6, &flag1);
    if (!ret) ret = read_ec(0x0751, &manual_profile);
    if (!ret) ret = read_ec(0x0741, &saved_oem);
    if (ret) return ret;
    /* Only the observed baseline. Don't take over somebody else's custom table. */
    if (!(features & 0x40) || flag0 || flag1 || (saved_oem != 0 && saved_oem != 4) || !profile_name(manual_profile))
        return -EOPNOTSUPP;
    ret = manual_health_locked();
    if (ret) return ret;
    for (i = 0; i < 96; i++) {
        ret = read_ec(0x0f00 + i, &saved_table[i]);
        if (ret) return ret;
        table_dirty[i] = false;
    }
    /* Uniwill universal table layout. Higher zones request full ventilation.
     * CPU first zone ends 85C, GPU 80C; software guard uses the same thresholds.
     */
    for (fan = 0; fan < 2; fan++) {
        offset = fan * 48;
        limit = fan ? 80 : 85;
        for (i = 0; i < 16; i++) {
            desired[offset + i] = i ? limit + i + 1 : limit;
            desired[offset + 16 + i] = i ? limit + i : 0;
            desired[offset + 32 + i] = i ? 200 : percent * 2;
        }
    }
    if (!try_module_get(THIS_MODULE)) return -ENODEV;
    manual_dirty = true; /* Set before the first potentially successful write. */
    manual_reason = "preparing";
    mod_delayed_work(system_wq, &manual_work, HZ);
    for (i = 0; i < 96; i++) {
        if (saved_table[i] == desired[i]) continue;
        table_dirty[i] = true;
        ret = checked_fan_write(0x0f00 + i, desired[i]);
        if (ret) goto fail;
    }
    ret = manual_health_locked(); /* Programming the table takes several seconds. */
    if (ret) goto fail;
    ret = set_fan_bits(0x0741, 1, 1); /* Host manual mode, preserve existing bit2. */
    if (!ret) ret = set_fan_bits(0x07c5, 0x80, 0x80);
    if (!ret) ret = set_fan_bits(0x07c6, 4, 4); /* Enable only fully verified table. */
    if (!ret) ret = write_fan_ec(0x1804, percent * 2);
    if (!ret) ret = write_fan_ec(0x1809, percent * 2);
    if (ret) goto fail;
    manual_running = true;
    manual_id++;
    if (!manual_id) manual_id++;
    manual_started = jiffies;
    manual_percent = percent;
    manual_reason = "manual";
    manual_deadline = jiffies + 30 * HZ;
    return 0;
fail:
    manual_reason = "setup_failed";
    stop_manual_locked();
    return ret;
}

static ssize_t fan_control_show(struct kobject *kobj, struct kobj_attribute *attr, char *buf)
{
    ssize_t n;
    unsigned long remaining = 0;
    mutex_lock(&snapshot_lock);
    if (manual_running && time_before(jiffies, manual_deadline))
        remaining = (manual_deadline - jiffies + HZ - 1) / HZ;
    n = sysfs_emit(buf, "{\"mode\":\"%s\",\"percent\":%u,\"seconds_remaining\":%lu,\"reason\":\"%s\",\"session_id\":%u,\"lease_supported\":true}\n",
        manual_dirty ? (manual_running ? "manual" : "restoring") : (boost_active ? "boost" : "auto"),
        manual_percent, remaining, manual_reason, manual_id);
    mutex_unlock(&snapshot_lock);
    return n;
}

static ssize_t fan_control_store(struct kobject *kobj, struct kobj_attribute *attr,
                                 const char *buf, size_t count)
{
    unsigned int percent, id;
    int ret;
    bool automatic = sysfs_streq(buf, "auto");
    bool renew = !strncmp(buf, "renew ", 6);
    bool cancel = !strncmp(buf, "auto ", 5);
    if (renew || cancel) {
        if (kstrtouint(buf + (renew ? 6 : 5), 10, &id)) return -EINVAL;
        mutex_lock(&snapshot_lock);
        if (id != manual_id || (renew && !manual_running)) ret = -ESTALE;
        else if (cancel) {
            manual_reason = "session_closed";
            ret = stop_manual_locked();
        } else {
            ret = manual_health_locked();
            if (!ret) manual_deadline = jiffies + 30 * HZ;
            else {
                manual_reason = "renewal_rejected";
                stop_manual_locked();
            }
        }
        mutex_unlock(&snapshot_lock);
        return ret ? ret : count;
    }
    if (!automatic && kstrtouint(buf, 10, &percent)) return -EINVAL;
    mutex_lock(&snapshot_lock);
    if (automatic) {
        manual_reason = "requested_auto";
        ret = stop_manual_locked();
        if (!ret) ret = stop_boost_locked();
    } else ret = start_manual_locked(percent);
    mutex_unlock(&snapshot_lock);
    return ret ? ret : count;
}
static struct kobj_attribute fan_control_attr = __ATTR(fan_control, 0644, fan_control_show, fan_control_store);
