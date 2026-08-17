Feature: Song features
  As a user of the Song Locator
  I want to add songs and find them again
  So that I can keep track of each song's format

  Scenario: Add a single song with its type
    Given the song database is ready
    When I add a song title with its type
    Then the song is saved with that type
    And adding the same type again is a no-op
    And a song without a type is stored as unset

  Scenario: Add many titles with one chosen type
    Given the song database is ready
    When I add many titles at once with a chosen type
    Then each new title is saved with that type
    And titles that already have that type are skipped
    And a doubled paste does not create a duplicate entry

  Scenario: Search for a song and find it
    Given the song database contains known songs
    When I search for an exact title
    Then the exact match is found
    When I search for a partial title
    Then matching songs are found
    When I search for a title with a typo
    Then the closest match is returned