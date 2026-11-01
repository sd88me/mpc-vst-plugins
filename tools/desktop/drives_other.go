//go:build !linux && !darwin && !windows

package main

// listDrives has no implementation on an OS this app doesn't target for a build; the browse-folders picker (not
// platform-specific) still works, just without the quick drive-pick list.
func listDrives() []driveEntry { return nil }
