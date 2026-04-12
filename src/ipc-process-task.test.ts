import { describe, it, expect, beforeEach } from 'vitest';

import {
  _initTestDatabase,
  createTask,
  getAllTasks,
  getTaskById,
  setRegisteredGroup,
} from './db.js';
import { processTaskIpc, IpcDeps } from './ipc.js';
import { RegisteredGroup } from './types.js';

const MAIN_GROUP: RegisteredGroup = {
  name: 'Main',
  folder: 'whatsapp_main',
  trigger: 'always',
  added_at: '2024-01-01T00:00:00.000Z',
  isMain: true,
};

const OTHER_GROUP: RegisteredGroup = {
  name: 'Other',
  folder: 'other-group',
  trigger: '@Andy',
  added_at: '2024-01-01T00:00:00.000Z',
};

let groups: Record<string, RegisteredGroup>;
let deps: IpcDeps;
let sentMessages: Array<{ jid: string; text: string }>;
let syncGroupsCalled: boolean;
let writeSnapshotCalled: boolean;
let tasksChangedCount: number;

beforeEach(() => {
  _initTestDatabase();

  sentMessages = [];
  syncGroupsCalled = false;
  writeSnapshotCalled = false;
  tasksChangedCount = 0;

  groups = {
    'main@g.us': MAIN_GROUP,
    'other@g.us': OTHER_GROUP,
  };

  setRegisteredGroup('main@g.us', MAIN_GROUP);
  setRegisteredGroup('other@g.us', OTHER_GROUP);

  deps = {
    sendMessage: async (jid, text) => {
      sentMessages.push({ jid, text });
    },
    registeredGroups: () => groups,
    registerGroup: (jid, group) => {
      groups[jid] = group;
      setRegisteredGroup(jid, group);
    },
    syncGroups: async () => {
      syncGroupsCalled = true;
    },
    getAvailableGroups: () => [],
    writeGroupsSnapshot: () => {
      writeSnapshotCalled = true;
    },
    onTasksChanged: () => {
      tasksChangedCount++;
    },
  };
});

// --- update_task ---

describe('update_task', () => {
  beforeEach(() => {
    createTask({
      id: 'task-to-update',
      group_folder: 'other-group',
      chat_jid: 'other@g.us',
      prompt: 'original prompt',
      schedule_type: 'once',
      schedule_value: '2025-06-01T00:00:00',
      context_mode: 'isolated',
      next_run: '2025-06-01T00:00:00.000Z',
      status: 'active',
      created_at: '2024-01-01T00:00:00.000Z',
    });
  });

  it('main group can update any task prompt', async () => {
    await processTaskIpc(
      {
        type: 'update_task',
        taskId: 'task-to-update',
        prompt: 'updated prompt',
      },
      'whatsapp_main',
      true,
      deps,
    );

    const task = getTaskById('task-to-update');
    expect(task!.prompt).toBe('updated prompt');
    expect(tasksChangedCount).toBe(1);
  });

  it('non-main group can update its own task', async () => {
    await processTaskIpc(
      {
        type: 'update_task',
        taskId: 'task-to-update',
        prompt: 'self update',
      },
      'other-group',
      false,
      deps,
    );

    expect(getTaskById('task-to-update')!.prompt).toBe('self update');
  });

  it('non-main group cannot update another groups task', async () => {
    createTask({
      id: 'task-main-owned',
      group_folder: 'whatsapp_main',
      chat_jid: 'main@g.us',
      prompt: 'main task',
      schedule_type: 'once',
      schedule_value: '2025-06-01T00:00:00',
      context_mode: 'isolated',
      next_run: '2025-06-01T00:00:00.000Z',
      status: 'active',
      created_at: '2024-01-01T00:00:00.000Z',
    });

    await processTaskIpc(
      {
        type: 'update_task',
        taskId: 'task-main-owned',
        prompt: 'hacked',
      },
      'other-group',
      false,
      deps,
    );

    expect(getTaskById('task-main-owned')!.prompt).toBe('main task');
  });

  it('update_task for non-existent task is a no-op', async () => {
    await processTaskIpc(
      {
        type: 'update_task',
        taskId: 'nonexistent',
        prompt: 'nope',
      },
      'whatsapp_main',
      true,
      deps,
    );

    expect(tasksChangedCount).toBe(0);
  });

  it('update_task without taskId is a no-op', async () => {
    await processTaskIpc(
      {
        type: 'update_task',
      },
      'whatsapp_main',
      true,
      deps,
    );

    expect(tasksChangedCount).toBe(0);
  });

  it('update_task can change schedule_type to cron and recompute next_run', async () => {
    await processTaskIpc(
      {
        type: 'update_task',
        taskId: 'task-to-update',
        schedule_type: 'cron',
        schedule_value: '0 9 * * *',
      },
      'whatsapp_main',
      true,
      deps,
    );

    const task = getTaskById('task-to-update');
    expect(task!.schedule_type).toBe('cron');
    expect(task!.schedule_value).toBe('0 9 * * *');
    expect(task!.next_run).toBeTruthy();
    expect(new Date(task!.next_run!).getTime()).toBeGreaterThan(
      Date.now() - 60000,
    );
  });

  it('update_task with invalid cron does not apply update', async () => {
    const originalNextRun = getTaskById('task-to-update')!.next_run;

    await processTaskIpc(
      {
        type: 'update_task',
        taskId: 'task-to-update',
        schedule_type: 'cron',
        schedule_value: 'invalid cron',
      },
      'whatsapp_main',
      true,
      deps,
    );

    const task = getTaskById('task-to-update');
    // Should remain unchanged since invalid cron breaks early
    expect(task!.schedule_type).toBe('once');
    expect(task!.next_run).toBe(originalNextRun);
  });

  it('update_task can change schedule_type to interval', async () => {
    const before = Date.now();

    await processTaskIpc(
      {
        type: 'update_task',
        taskId: 'task-to-update',
        schedule_type: 'interval',
        schedule_value: '60000',
      },
      'whatsapp_main',
      true,
      deps,
    );

    const task = getTaskById('task-to-update');
    expect(task!.schedule_type).toBe('interval');
    const nextRun = new Date(task!.next_run!).getTime();
    expect(nextRun).toBeGreaterThanOrEqual(before + 60000 - 1000);
  });
});

// --- pause_task sends notification ---

describe('pause_task notifications', () => {
  it('pause_task sends admin notification', async () => {
    createTask({
      id: 'task-notify',
      group_folder: 'other-group',
      chat_jid: 'other@g.us',
      prompt: 'notify task',
      schedule_type: 'once',
      schedule_value: '2025-06-01T00:00:00',
      context_mode: 'isolated',
      next_run: '2025-06-01T00:00:00.000Z',
      status: 'active',
      created_at: '2024-01-01T00:00:00.000Z',
    });

    await processTaskIpc(
      { type: 'pause_task', taskId: 'task-notify' },
      'other-group',
      false,
      deps,
    );

    expect(getTaskById('task-notify')!.status).toBe('paused');
    // Should have attempted to send admin notification
    expect(sentMessages.length).toBeGreaterThanOrEqual(1);
    expect(sentMessages[0].text).toContain('task-notify');
    expect(sentMessages[0].text).toContain('paused');
    expect(tasksChangedCount).toBe(1);
  });
});

// --- schedule_task calls onTasksChanged ---

describe('schedule_task callbacks', () => {
  it('calls onTasksChanged after creating task', async () => {
    await processTaskIpc(
      {
        type: 'schedule_task',
        prompt: 'test task',
        schedule_type: 'once',
        schedule_value: '2025-06-01T00:00:00',
        targetJid: 'other@g.us',
      },
      'whatsapp_main',
      true,
      deps,
    );

    expect(tasksChangedCount).toBe(1);
    expect(getAllTasks()).toHaveLength(1);
  });

  it('does not call onTasksChanged when missing required fields', async () => {
    await processTaskIpc(
      {
        type: 'schedule_task',
        prompt: 'no target',
        // missing schedule_type, schedule_value, targetJid
      },
      'whatsapp_main',
      true,
      deps,
    );

    expect(tasksChangedCount).toBe(0);
  });
});

// --- refresh_groups ---

describe('refresh_groups', () => {
  it('main group triggers syncGroups and writeGroupsSnapshot', async () => {
    await processTaskIpc(
      { type: 'refresh_groups' },
      'whatsapp_main',
      true,
      deps,
    );

    expect(syncGroupsCalled).toBe(true);
    expect(writeSnapshotCalled).toBe(true);
  });

  it('non-main group refresh is blocked', async () => {
    await processTaskIpc(
      { type: 'refresh_groups' },
      'other-group',
      false,
      deps,
    );

    expect(syncGroupsCalled).toBe(false);
    expect(writeSnapshotCalled).toBe(false);
  });
});

// --- Unknown IPC type ---

describe('unknown IPC type', () => {
  it('unknown type does not crash', async () => {
    await processTaskIpc(
      { type: 'totally_unknown' },
      'whatsapp_main',
      true,
      deps,
    );
    // No error thrown, no side effects
    expect(tasksChangedCount).toBe(0);
  });
});

// --- schedule_task with custom taskId ---

describe('schedule_task taskId', () => {
  it('uses provided taskId', async () => {
    await processTaskIpc(
      {
        type: 'schedule_task',
        taskId: 'my-custom-id',
        prompt: 'custom id task',
        schedule_type: 'once',
        schedule_value: '2025-06-01T00:00:00',
        targetJid: 'other@g.us',
      },
      'whatsapp_main',
      true,
      deps,
    );

    const task = getTaskById('my-custom-id');
    expect(task).toBeDefined();
    expect(task!.prompt).toBe('custom id task');
  });

  it('generates taskId when not provided', async () => {
    await processTaskIpc(
      {
        type: 'schedule_task',
        prompt: 'auto id task',
        schedule_type: 'once',
        schedule_value: '2025-06-01T00:00:00',
        targetJid: 'other@g.us',
      },
      'whatsapp_main',
      true,
      deps,
    );

    const tasks = getAllTasks();
    expect(tasks).toHaveLength(1);
    expect(tasks[0].id).toMatch(/^task-/);
  });
});

// --- register_group sets correct fields ---

describe('register_group field handling', () => {
  it('does not allow isMain to be set via IPC', async () => {
    await processTaskIpc(
      {
        type: 'register_group',
        jid: 'new@g.us',
        name: 'Sneaky',
        folder: 'sneaky-group',
        trigger: '@Andy',
        // isMain is not part of the data type, but even if passed in containerConfig etc,
        // the code explicitly constructs without isMain
      },
      'whatsapp_main',
      true,
      deps,
    );

    const registered = groups['new@g.us'];
    expect(registered).toBeDefined();
    expect(registered.isMain).toBeUndefined();
  });

  it('passes containerConfig and requiresTrigger', async () => {
    await processTaskIpc(
      {
        type: 'register_group',
        jid: 'cfg@g.us',
        name: 'Configured',
        folder: 'cfg-group',
        trigger: '@Bot',
        requiresTrigger: true,
        containerConfig: { image: 'custom:latest' } as any,
      },
      'whatsapp_main',
      true,
      deps,
    );

    const registered = groups['cfg@g.us'];
    expect(registered).toBeDefined();
    expect(registered.requiresTrigger).toBe(true);
    expect(registered.containerConfig).toEqual({ image: 'custom:latest' });
  });
});
