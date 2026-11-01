//go:build windows

package main

import (
	"fmt"
	"syscall"
	"unsafe"
)

// listDrives enumerates drive letters and keeps the removable and fixed ones (not CD-ROMs, network shares, or
// drives with nothing in them), via plain syscalls -- no extra dependency for this one lookup. C: is always
// skipped: never a sensible pick for "where to write the stick".
func listDrives() []driveEntry {
	kernel32 := syscall.NewLazyDLL("kernel32.dll")
	getLogicalDrives := kernel32.NewProc("GetLogicalDrives")
	getDriveType := kernel32.NewProc("GetDriveTypeW")

	ret, _, _ := getLogicalDrives.Call()
	mask := uint32(ret)
	const driveRemovable = 2
	const driveFixed = 3
	var out []driveEntry
	for i := 0; i < 26; i++ {
		if mask&(1<<uint(i)) == 0 {
			continue
		}
		letter := string(rune('A' + i))
		if letter == "C" {
			continue
		}
		root := letter + `:\`
		p, err := syscall.UTF16PtrFromString(root)
		if err != nil {
			continue
		}
		t, _, _ := getDriveType.Call(uintptr(unsafe.Pointer(p)))
		switch uint32(t) {
		case driveRemovable:
			out = append(out, driveEntry{Label: fmt.Sprintf("%s: (removable drive)", letter), Path: root})
		case driveFixed:
			out = append(out, driveEntry{Label: fmt.Sprintf("%s: drive", letter), Path: root})
		}
	}
	return out
}
