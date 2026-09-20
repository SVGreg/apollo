/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

export interface AppReference {
  name: string;
  icon: string;
  pkg?: string;
  category?: string;
}

export type SuggestionCategory =
  | 'all'
  | 'flash'
  | 'pro'
  | 'cross_app'
  | 'monitor';

export interface SmartSuggestion {
  id: string;
  title: string;
  description: string;
  goal: string;
  profile: 'flash' | 'pro';
  category: 'flash' | 'pro' | 'cross_app' | 'monitor';
  tag: string;
  apps: AppReference[];
  requiredPackages?: string[];
  matchMode?: 'any' | 'all';
  priority?: number;
}

/**
 * Recognized iOS App Registry (bundle ids). Simulators ship the built-in apps below;
 * physical devices add App Store apps on top.
 */
export const APP_REGISTRY: Record<string, AppReference> = {
  'com.apple.Preferences': { name: 'Settings', icon: 'settings', pkg: 'com.apple.Preferences', category: 'system' },
  'com.apple.mobilesafari': { name: 'Safari', icon: 'public', pkg: 'com.apple.mobilesafari', category: 'browser' },
  'com.apple.mobilecal': { name: 'Calendar', icon: 'calendar_month', pkg: 'com.apple.mobilecal', category: 'productivity' },
  'com.apple.reminders': { name: 'Reminders', icon: 'checklist', pkg: 'com.apple.reminders', category: 'productivity' },
  'com.apple.MobileAddressBook': { name: 'Contacts', icon: 'contacts', pkg: 'com.apple.MobileAddressBook', category: 'productivity' },
  'com.apple.Maps': { name: 'Maps', icon: 'explore', pkg: 'com.apple.Maps', category: 'navigation' },
  'com.apple.mobileslideshow': { name: 'Photos', icon: 'photo_library', pkg: 'com.apple.mobileslideshow', category: 'media' },
  'com.apple.MobileSMS': { name: 'Messages', icon: 'chat', pkg: 'com.apple.MobileSMS', category: 'communication' },
  'com.apple.DocumentsApp': { name: 'Files', icon: 'folder', pkg: 'com.apple.DocumentsApp', category: 'utility' },
  'com.apple.mobilenotes': { name: 'Notes', icon: 'note_alt', pkg: 'com.apple.mobilenotes', category: 'productivity' },
  'com.apple.mobiletimer': { name: 'Clock', icon: 'timer', pkg: 'com.apple.mobiletimer', category: 'utility' },
  'com.apple.mobilemail': { name: 'Mail', icon: 'mail', pkg: 'com.apple.mobilemail', category: 'productivity' },
  'com.apple.weather': { name: 'Weather', icon: 'partly_cloudy_day', pkg: 'com.apple.weather', category: 'utility' },
  'com.apple.Health': { name: 'Health', icon: 'favorite', pkg: 'com.apple.Health', category: 'lifestyle' },
  'com.apple.news': { name: 'News', icon: 'newspaper', pkg: 'com.apple.news', category: 'entertainment' },
  'com.apple.shortcuts': { name: 'Shortcuts', icon: 'bolt', pkg: 'com.apple.shortcuts', category: 'tools' },
  'com.apple.Passwords': { name: 'Passwords', icon: 'key', pkg: 'com.apple.Passwords', category: 'tools' },
  'com.apple.Bridge': { name: 'Watch', icon: 'watch', pkg: 'com.apple.Bridge', category: 'utility' }
};

/**
 * Curated task presets: the built-in apps present on every iOS 26 simulator, plus a few
 * that only exist on physical devices (Notes, Clock, Mail) gated by requiredPackages.
 */
export const SMART_TASK_LIBRARY: SmartSuggestion[] = [
  {
    id: 'settings_about',
    title: 'Read Device Info',
    description: 'Navigate Settings > General > About and report iOS version and model',
    goal: 'Open Settings, go to General > About and tell me the iOS version and the model name.',
    profile: 'flash',
    category: 'flash',
    tag: 'Settings',
    apps: [{ name: 'Settings', icon: 'settings', pkg: 'com.apple.Preferences' }],
    requiredPackages: ['com.apple.Preferences'],
    priority: 98
  },
  {
    id: 'settings_bold_text',
    title: 'Toggle Bold Text',
    description: 'Turn on Bold Text under Accessibility > Display & Text Size',
    goal: 'In Settings, turn on Bold Text under Accessibility > Display & Text Size, then confirm it is on.',
    profile: 'flash',
    category: 'flash',
    tag: 'Settings',
    apps: [{ name: 'Settings', icon: 'settings', pkg: 'com.apple.Preferences' }],
    requiredPackages: ['com.apple.Preferences'],
    priority: 90
  },
  {
    id: 'reminders_add',
    title: 'Add a Reminder',
    description: 'Create a new reminder in the Reminders app',
    goal: "Open Reminders and add a new reminder titled 'Buy oat milk'.",
    profile: 'flash',
    category: 'flash',
    tag: 'Reminders',
    apps: [{ name: 'Reminders', icon: 'checklist', pkg: 'com.apple.reminders' }],
    requiredPackages: ['com.apple.reminders'],
    priority: 92
  },
  {
    id: 'contacts_add',
    title: 'Create a Contact',
    description: 'Add a new contact with first and last name and save it',
    goal: 'Open Contacts and create a new contact with first name Ada and last name Lovelace, then save it.',
    profile: 'flash',
    category: 'flash',
    tag: 'Contacts',
    apps: [{ name: 'Contacts', icon: 'contacts', pkg: 'com.apple.MobileAddressBook' }],
    requiredPackages: ['com.apple.MobileAddressBook'],
    priority: 88
  },
  {
    id: 'calendar_event',
    title: 'Schedule an Event',
    description: 'Create a calendar event for tomorrow afternoon',
    goal: "Open Calendar and create an event called 'Apollo demo' tomorrow at 3 PM.",
    profile: 'flash',
    category: 'flash',
    tag: 'Calendar',
    apps: [{ name: 'Calendar', icon: 'calendar_month', pkg: 'com.apple.mobilecal' }],
    requiredPackages: ['com.apple.mobilecal'],
    priority: 86
  },
  {
    id: 'safari_heading',
    title: 'Read a Web Page',
    description: 'Open a URL in Safari and report the page heading',
    goal: 'Open Safari, go to example.com and tell me the page heading.',
    profile: 'flash',
    category: 'flash',
    tag: 'Safari',
    apps: [{ name: 'Safari', icon: 'public', pkg: 'com.apple.mobilesafari' }],
    requiredPackages: ['com.apple.mobilesafari'],
    priority: 85
  },
  {
    id: 'maps_search',
    title: 'Find a Place',
    description: 'Search Apple Maps and open the top result',
    goal: 'Open Maps, search for "Golden Gate Bridge" and open the top result to read its details.',
    profile: 'flash',
    category: 'flash',
    tag: 'Maps',
    apps: [{ name: 'Maps', icon: 'explore', pkg: 'com.apple.Maps' }],
    requiredPackages: ['com.apple.Maps'],
    priority: 80
  },
  {
    id: 'pro_calendar_to_reminder',
    title: 'Event to Reminder',
    description: 'Read the next Calendar event and create a matching Reminder',
    goal: 'Open Calendar, find the next upcoming event, then open Reminders and add a reminder with the same title one hour before the event.',
    profile: 'pro',
    category: 'cross_app',
    tag: 'Calendar + Reminders',
    apps: [
      { name: 'Calendar', icon: 'calendar_month', pkg: 'com.apple.mobilecal' },
      { name: 'Reminders', icon: 'checklist', pkg: 'com.apple.reminders' }
    ],
    requiredPackages: ['com.apple.mobilecal', 'com.apple.reminders'],
    matchMode: 'all',
    priority: 84
  },
  {
    id: 'pro_contact_to_maps',
    title: 'Contact Address in Maps',
    description: 'Look up a contact and open their address in Maps',
    goal: 'Open Contacts, find the first contact that has an address, then open that address in Maps and report the estimated driving time from the current location.',
    profile: 'pro',
    category: 'cross_app',
    tag: 'Contacts + Maps',
    apps: [
      { name: 'Contacts', icon: 'contacts', pkg: 'com.apple.MobileAddressBook' },
      { name: 'Maps', icon: 'explore', pkg: 'com.apple.Maps' }
    ],
    requiredPackages: ['com.apple.MobileAddressBook', 'com.apple.Maps'],
    matchMode: 'all',
    priority: 82
  },
  {
    id: 'pro_settings_audit',
    title: 'Subsystem Health & Crash Probe',
    description: 'Traverse Settings submenus and verify screens open without errors',
    goal: 'Open Settings and visit General, Accessibility, Display & Brightness and Privacy & Security. For each, open two sub-screens, confirm they render, go back, and report any screen that failed to open.',
    profile: 'pro',
    category: 'pro',
    tag: 'Settings QA',
    apps: [{ name: 'Settings', icon: 'settings', pkg: 'com.apple.Preferences' }],
    requiredPackages: ['com.apple.Preferences'],
    priority: 78
  },
  {
    id: 'photos_open',
    title: 'Browse Photos',
    description: 'Open the Photos library and describe the most recent item',
    goal: 'Open Photos, go to the Library, open the most recent photo and describe what it shows.',
    profile: 'flash',
    category: 'flash',
    tag: 'Photos',
    apps: [{ name: 'Photos', icon: 'photo_library', pkg: 'com.apple.mobileslideshow' }],
    requiredPackages: ['com.apple.mobileslideshow'],
    priority: 70
  },
  {
    id: 'notes_create',
    title: 'Write a Note',
    description: 'Create a note (physical devices; the simulator has no Notes app)',
    goal: "Open Notes and create a new note with the title 'Apollo' and the text 'hello from the agent'.",
    profile: 'flash',
    category: 'flash',
    tag: 'Notes',
    apps: [{ name: 'Notes', icon: 'note_alt', pkg: 'com.apple.mobilenotes' }],
    requiredPackages: ['com.apple.mobilenotes'],
    priority: 60
  },
  {
    id: 'clock_alarm',
    title: 'Set an Alarm',
    description: 'Create a 6:45 AM alarm (physical devices; the simulator has no Clock app)',
    goal: "Open Clock and set a 6:45 AM alarm labeled 'Gym'.",
    profile: 'flash',
    category: 'flash',
    tag: 'Clock',
    apps: [{ name: 'Clock', icon: 'timer', pkg: 'com.apple.mobiletimer' }],
    requiredPackages: ['com.apple.mobiletimer'],
    priority: 58
  },
  {
    id: 'monitor_battery',
    title: 'Watch Battery Level',
    description: 'Monitor: report the battery level shown in Settings every few minutes',
    goal: 'Open Settings > Battery, read the current level, wait 2 minutes, read it again, and report both values.',
    profile: 'flash',
    category: 'monitor',
    tag: 'Monitor',
    apps: [{ name: 'Settings', icon: 'settings', pkg: 'com.apple.Preferences' }],
    requiredPackages: ['com.apple.Preferences'],
    priority: 50
  }
];
