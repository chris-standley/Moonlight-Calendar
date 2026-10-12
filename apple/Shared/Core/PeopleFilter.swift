import Foundation

extension Set where Element == String {
    /// Tapping a person in the calendar's people filter (the set holds the hidden people). From everyone shown, a tap
    /// shows only that person; after that, taps add or remove people, and removing the last one shows everyone again.
    mutating func tapPerson(_ id: String, everyone: [String]) {
        if isEmpty {
            self = Set(everyone.filter { $0 != id })
        } else if contains(id) {
            remove(id)
        } else {
            insert(id)
            if isSuperset(of: everyone) { removeAll() }
        }
    }
}
